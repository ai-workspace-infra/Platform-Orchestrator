#!/usr/bin/env python3
"""Offline falsification of authenticated transport; no live acceptance claim."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import warnings
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[3]
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
T=load('trusted_test_adapter',ROOT/'.github/scripts/feature-lane/trusted.py')
F=load('gate_fixture',ROOT/'scripts/tests/control_plane/feature_lane_gate_test.py')


class TrustedTest(unittest.TestCase):
    def setUp(self):
        self.c,self.policy,self.prs,self.receipt,self.run,self.auth=F.fixture()
        self.policy['authorization_url_prefix']=self.c['task_url']+'#'
        self.policy.update(task_url=self.c['task_url'], authorization={'kind':'issue_comment','repository':'example/accounts','issue':1,'comment_id':9})
        self.policy['acceptance_owner'].update(run_id=42,attempt=1,event='workflow_dispatch',artifact_id=101,
            artifact_name='acceptance-42-1',filename='receipt.json')
        self.policy['builds']={'example/accounts':dict(repository='example/accounts',workflow='build.yml',sha='a'*40,
            event='pull_request',run_id=11,attempt=1,artifact_id=102,artifact_name='build-11-1',filename='manifest.json')}
        self.documents={101:self.receipt,102:{'repository':'example/accounts','source_sha':'a'*40,'image':self.c['sources'][0]['image']}}
        self.metadata={};self.archives={};self.rawruns={}
        for loc in [self.policy['acceptance_owner'],*self.policy['builds'].values()]:
            self.rawruns[loc['run_id']]=dict(repository={'full_name':loc['repository']},head_repository={'full_name':loc['repository']},
                path=loc['workflow'],head_sha=loc['sha'],event=loc['event'],id=loc['run_id'],run_attempt=loc['attempt'],status='completed',conclusion='success')
            self.archive(loc['artifact_id'],loc['filename'],json.dumps(self.documents[loc['artifact_id']]))
            self.metadata[loc['artifact_id']].update(name=loc['artifact_name'],workflow_run={'id':loc['run_id']})
        self.comment={'id':9,'user':{'login':'human','type':'User'},'author_association':'MEMBER',
            'issue_url':'https://api.github.com/repos/example/accounts/issues/1',
            'html_url':self.policy['authorization_url_prefix']+'issuecomment-9',
            'body':'APPROVE feature-candidate '+T.gate.identity(self.c)+' action=merge',
            'created_at':'2026-10-26T01:00:00Z','updated_at':'2026-10-26T01:00:00Z'}
        self.comments=[self.comment];self.policy_drift=False;self.main_status='ahead'
        self.rawpr={'base':{'repo':{'full_name':'example/accounts'},'ref':'main'},'head':{'repo':{'full_name':'example/accounts'},'sha':'a'*40},
            'number':2,'state':'open','merged':False,'merge_commit_sha':None}

    def archive(self,aid,name,body,extra=None):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr(name,body)
            if extra:z.writestr(extra,'bad')
        raw=stream.getvalue();self.archives[aid]=raw
        self.metadata.setdefault(aid,{}).update(id=aid,expired=False,size_in_bytes=len(raw),digest='sha256:'+hashlib.sha256(raw).hexdigest())

    def api(self,path,binary=False):
        if binary:
            self.assertRegex(path,r'^repos/(example/accounts|example/playbooks)/actions/artifacts/[0-9]+/zip$')
            return self.archives[int(path.split('/')[-2])]
        if path.endswith('/git/ref/heads/main'):return {'object':{'sha':'d'*40}}
        if '/compare/' in path:return {'status':self.main_status}
        if '/contents/' in path:return {'type':'file','path':T.POLICY_PATH,'size':1000,'sha':('c' if self.policy_drift and path.endswith('d'*40) else 'b')*40,'content':base64.b64encode(json.dumps(self.policy).encode()).decode()}
        if '/pulls/2' in path:return self.rawpr
        if '/git/commits/' in path:return {'tree':{'sha':'b'*40}}
        if '/actions/runs/' in path:return self.rawruns[int(path.split('/')[-1])]
        if '/actions/artifacts/' in path:return self.metadata[int(path.split('/')[-1])]
        if '/comments?' in path:return self.comments
        if path.endswith('/issues/1'):return {'number':1,'url':'https://api.github.com/repos/example/accounts/issues/1'}
        raise AssertionError('unexpected API route')

    def decide(self,stage='merge'):
        with patch.object(T.reader,'api',side_effect=self.api):return T.verified(self.c,stage,'f'*40)

    def test_verified_retrieval_never_executes(self):
        r=self.decide();self.assertEqual(r['status'],'VERIFIED_GATE');self.assertFalse(r['dispatch_authorized']);self.assertEqual(r['execution'],'NOT_RUN')

    def test_policy_must_be_reviewed_main_not_pr_or_local_json(self):
        for field,bad in [('policy_drift',True),('main_status','diverged')]:
            with self.subTest(field=field):
                setattr(self,field,bad)
                with self.assertRaises(T.gate.Blocked):self.decide()
                self.setUp()
        with self.assertRaises(F.gate.Blocked):F.gate.gate(self.c,self.policy,'merge',self.prs,policy_commit='f'*40)

    def test_missing_run_is_blocked_not_stubbed(self):
        self.rawruns.pop(42)
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_wrong_run_attempt_sha_workflow_or_fork_producer(self):
        for key,bad in [('id',99),('run_attempt',2),('head_sha','b'*40),('path','foreign.yml'),('head_repository',{'full_name':'fork/owner'})]:
            with self.subTest(key=key):
                self.rawruns[42][key]=bad
                with self.assertRaises(T.gate.Blocked):self.decide()
                self.setUp()

    def test_expired_mixedrun_oversized_or_tampered_archive(self):
        for key,bad in [('expired',True),('workflow_run',{'id':99}),('size_in_bytes',3_000_000),('digest','sha256:'+'0'*64)]:
            with self.subTest(key=key):
                self.metadata[101][key]=bad
                with self.assertRaises(T.gate.Blocked):self.decide()
                self.setUp()
        self.archives[101]=b'x'*2_000_001
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_zip_paths_links_duplicates_and_unpacked_size_rejected(self):
        for name in ('../escape','/absolute','bad\\entry'):
            self.archive(101,'receipt.json',json.dumps(self.receipt),name)
            with self.subTest(name=name),self.assertRaises(T.gate.Blocked):self.decide()
        self.setUp();self.archive(101,'receipt.json','x'*2_000_001)
        with self.assertRaises(T.gate.Blocked):self.decide()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('receipt.json',json.dumps(self.receipt))
            symlink=zipfile.ZipInfo('link');symlink.external_attr=0o120777<<16;z.writestr(symlink,'/etc/passwd')
        self.archives[101]=stream.getvalue();self.metadata[101]['digest']='sha256:'+hashlib.sha256(stream.getvalue()).hexdigest()
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_build_manifest_cannot_lie_about_image_or_source(self):
        for field,bad in [('source_sha','d'*40),('image','other@sha256:'+'a'*64),('repository','foreign/repo')]:
            self.documents[102][field]=bad;self.archive(102,'manifest.json',json.dumps(self.documents[102]))
            with self.subTest(field=field),self.assertRaises(T.gate.Blocked):self.decide()
            self.setUp()

    def test_authorization_edited_deleted_wrong_actor_or_revoked(self):
        for field,bad in [('updated_at','later'),('author_association','NONE'),('user',{'login':'human','type':'Bot'}),('body','approved=true')]:
            self.comment[field]=bad
            with self.subTest(field=field),self.assertRaises(T.gate.Blocked):self.decide()
            self.setUp()
        self.comments=[]
        with self.assertRaises(T.gate.Blocked):self.decide()
        self.setUp();self.comments.append(dict(self.comment,id=10,body='REVOKE feature-candidate '+T.gate.identity(self.c)))
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_attempt_two_artifact_and_receipt_are_bound_together(self):
        loc=self.policy['acceptance_owner'];loc['attempt']=2;loc['artifact_name']='acceptance-42-2'
        self.rawruns[42]['run_attempt']=2;self.metadata[101]['name']=loc['artifact_name']
        self.receipt['run_attempt']=2;self.archive(101,'receipt.json',json.dumps(self.receipt))
        self.assertEqual(self.decide()['status'],'VERIFIED_GATE')
        self.receipt['run_attempt']=1;self.archive(101,'receipt.json',json.dumps(self.receipt))
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_duplicate_receipt_and_compressed_expansion_are_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            self.archive(101,'receipt.json',json.dumps(self.receipt),'receipt.json')
        with self.assertRaises(T.gate.Blocked):self.decide()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('receipt.json','x'*4_000_001)
        self.archives[101]=stream.getvalue();self.metadata[101].update(size_in_bytes=len(stream.getvalue()),digest='sha256:'+hashlib.sha256(stream.getvalue()).hexdigest())
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_public_gate_uses_retrieval_without_accepting_raw_json(self):
        with patch.object(T.reader,'api',side_effect=self.api):
            # The public loader imports its own reader; patch the adapter load
            # boundary only, not the evaluator or authenticated retrieval code.
            with patch('importlib.util.module_from_spec', return_value=T), patch('importlib.machinery.SourceFileLoader.exec_module'):
                result=F.gate.gate(self.c,stage='merge',policy_commit='f'*40)
        self.assertEqual(result['status'],'VERIFIED_GATE')

    def test_download_uses_only_authenticated_github_artifact_id_endpoint(self):
        self.metadata[101]['archive_download_url']='https://attacker.invalid/archive'
        self.assertEqual(self.decide()['status'],'VERIFIED_GATE')
        with self.assertRaises(ValueError):T.reader.api('https://attacker.invalid/archive',binary=True)

    def test_transport_bounds_actual_output_even_if_metadata_lies(self):
        process=subprocess.Popen([sys.executable,'-c','import sys;sys.stdout.buffer.write(b"x"*2000001)'],stdout=subprocess.PIPE)
        with patch.object(T.reader.subprocess,'Popen',return_value=process):
            with self.assertRaisesRegex(ValueError,'size limit'):T.reader.api('repos/example/accounts/actions/artifacts/1/zip',binary=True)
        self.assertIsNotNone(process.poll())

    def test_unconfigured_optional_authorization_source_is_blocked(self):
        self.policy.pop('authorization')
        with self.assertRaisesRegex(T.gate.Blocked,'authorization source'):self.decide()

    def test_uat_retrieves_explicit_merged_artifact_mapping(self):
        self.rawpr.update(state='closed',merged=True,merge_commit_sha='e'*40)
        loc=dict(repository='example/accounts',workflow='build.yml',sha='e'*40,event='push',run_id=12,
                 attempt=1,artifact_id=103,artifact_name='merge-12-1',filename='manifest.json')
        self.policy['merge_builds']={'example/accounts':loc}
        self.rawruns[12]=dict(self.rawruns[11],id=12,head_sha='e'*40,event='push')
        proof={'repository':'example/accounts','merge_sha':'e'*40,'source_sha':'a'*40,
               'image':self.c['sources'][0]['image'],'manifest_sha256':'c'*64}
        self.archive(103,'manifest.json',json.dumps(proof));self.metadata[103].update(name=loc['artifact_name'],workflow_run={'id':12})
        self.comment['body']=self.comment['body'].replace('action=merge','action=uat')
        result=self.decide('uat');self.assertEqual(result['namespace'],'web-saas-uat')
        proof['image']='other@sha256:'+'d'*64;self.archive(103,'manifest.json',json.dumps(proof))
        with self.assertRaises(T.gate.Blocked):self.decide('uat')

    def test_wrong_pr_head_or_fork_rejected(self):
        self.rawpr['head']['repo']['full_name']='fork/accounts'
        with self.assertRaises(T.gate.Blocked):self.decide()

if __name__=='__main__':unittest.main()
