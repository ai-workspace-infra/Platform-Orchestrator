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
    def test_gitops_domain_binding_rejects_moved_main_and_changed_bytes(self):
        path = 'docs/features/tagged-sit-domain-contract.yaml'
        candidate = {'gitops': {'repository': 'example/gitops', 'sha': 'd' * 40, 'domain_sha256': 'a' * 64},
                     'configurations': []}
        policy = {'gitops_repository': 'example/gitops', 'gitops_domain_contract_path': path}
        with patch.object(T, 'file_at', return_value='a' * 64), \
             patch.object(T.reader, 'api', return_value={'object': {'type': 'commit', 'sha': 'd' * 40}}):
            T.verify_gitops_domain(candidate, policy, 'sit')
            with patch.object(T.reader, 'api', return_value={'object': {'type': 'commit', 'sha': 'e' * 40}}):
                with self.assertRaisesRegex(T.gate.Blocked, 'Main moved'):
                    T.verify_gitops_domain(candidate, policy, 'sit')
            candidate['configurations'] = [{'repository': 'example/gitops', 'sha': 'd' * 40,
                                             'paths': {path: 'a' * 64}}]
            T.verify_gitops_domain(candidate, policy, 'sit')
            candidate['configurations'][0]['paths'][path] = 'b' * 64
            with self.assertRaisesRegex(T.gate.Blocked, 'configuration PR'):
                T.verify_gitops_domain(candidate, policy, 'sit')
        with patch.object(T, 'file_at', return_value='b' * 64):
            with self.assertRaisesRegex(T.gate.Blocked, 'declaration differs'):
                T.verify_gitops_domain(candidate, policy, 'sit')

    def test_evidence_transport_selects_token_by_fixed_api_owner(self):
        with patch.dict('os.environ', {'FEATURE_GH_TOKEN_INFRA': 'infra-token',
                                       'FEATURE_GH_TOKEN_SERVICES': 'services-token'}, clear=True):
            with patch.object(T, '_authenticated_api', return_value={}) as api:
                T.feature_api('repos/ai-workspace-services/accounts/actions/artifacts/1/zip', binary=True)
                self.assertEqual(api.call_args.kwargs, {'binary': True, 'token': 'services-token'})
                T.feature_api('repos/ai-workspace-infra/gitops/git/ref/heads/main')
                self.assertEqual(api.call_args.kwargs, {'binary': False, 'token': 'infra-token'})
                T.feature_api('repos/example/accounts/actions/runs/1')
                self.assertEqual(api.call_args.kwargs, {'binary': False, 'token': None})

    def test_main_image_manifest_binds_authenticated_run_and_source(self):
        source = {'repository': 'example/accounts', 'kind': 'baseline', 'sha': 'a' * 40,
                  'image': 'example/accounts@sha256:' + 'b' * 64}
        run = {'event': 'push', 'head_branch': 'main', 'id': 11, 'attempt': 1}
        proof = {'schema': 'main-image-build/v1', 'source_repository': source['repository'],
                 'source_sha': source['sha'], 'image': source['image'], 'event': 'push',
                 'ref': 'refs/heads/main', 'run_id': 11, 'attempt': 1}
        T.verify_build_manifest(proof, run, source)
        for key, value in [('source_repository', 'example/other'), ('source_sha', 'c' * 40),
                           ('image', 'other'), ('event', 'pull_request'), ('ref', 'refs/heads/dev'),
                           ('run_id', 12), ('attempt', 2), ('repository', 'example/other')]:
            with self.subTest(key=key):
                changed = dict(proof, **{key: value})
                with self.assertRaises(T.gate.Blocked):
                    T.verify_build_manifest(changed, run, source)
        with self.assertRaises(T.gate.Blocked):
            T.verify_build_manifest(proof, run, dict(source, kind='feature'))
        with self.assertRaises(T.gate.Blocked):
            T.verify_build_manifest(proof, dict(run, head_branch='other'), source)

    def setUp(self):
        self.c,self.policy,self.prs,self.receipt,self.run,self.auth=F.fixture()
        self.policy['authorization_url_prefix']=self.c['task_url']+'#'
        self.policy.update(task_url=self.c['task_url'], authorization={'kind':'issue_comment','repository':'example/accounts','issue':1,'comment_id':9})
        self.policy['acceptance_owner'].update(run_id=42,attempt=1,event='workflow_dispatch',artifact_id=101,
            artifact_name='acceptance-42-1',filename='receipt.json')
        self.policy['builds']={'example/accounts':dict(repository='example/accounts',workflow='build.yml',sha='a'*40,
            event='pull_request',run_id=11,attempt=1,artifact_id=102,artifact_name='build-11-1',filename='manifest.json')}
        self.documents={101:self.receipt,102:{'repository':'example/accounts','source_sha':'a'*40,'image':self.c['sources'][0]['image']}}
        self.metadata={};self.archives={};self.rawruns={};self.files={};self.config_rawpr=None
        for loc in [self.policy['acceptance_owner'],*self.policy['builds'].values()]:
            self.rawruns[loc['run_id']]=dict(repository={'full_name':loc['repository']},head_repository={'full_name':loc['repository']},
                path=loc['workflow'],head_sha=loc['sha'],event=loc['event'],id=loc['run_id'],run_attempt=loc['attempt'],status='completed',conclusion='success')
            self.archive(loc['artifact_id'],loc['filename'],json.dumps(self.documents[loc['artifact_id']]))
            self.metadata[loc['artifact_id']].update(name=loc['artifact_name'],workflow_run={'id':loc['run_id']})
        self.selectors={'builds':{'example/accounts':{'run_id':11,'attempt':1,'artifact_id':102}},
                        'acceptance':{'run_id':42,'attempt':1,'artifact_id':101},'authorization':{'issue':1,'comment_id':9}}
        for key in ('run_id','attempt','artifact_id','artifact_name'):
            self.policy['acceptance_owner'].pop(key)
        self.policy['acceptance_owner']['artifact_prefix']='acceptance'
        self.policy['build_owners']={'example/accounts':{'repository':'example/accounts','workflow':'build.yml',
                                    'event':'pull_request','artifact_prefix':'build','filename':'manifest.json'}}
        self.policy.pop('builds');self.policy.pop('task_url');self.policy.pop('authorization_url_prefix')
        self.policy['task_repositories']=['example/accounts']
        self.policy['authorization']={'kind':'issue_comment','repository':'example/accounts'}
        self.comment={'id':9,'user':{'login':'human','type':'User'},'author_association':'MEMBER',
            'issue_url':'https://api.github.com/repos/example/accounts/issues/1',
            'html_url':self.c['task_url']+'#issuecomment-9',
            'body':'APPROVE feature-candidate '+T.gate.identity(self.c)+' action=merge',
            'created_at':'2026-10-26T01:00:00Z','updated_at':'2026-10-26T01:00:00Z'}
        self.comments=[self.comment];self.policy_drift=False;self.main_status='ahead'
        self.rawpr={'base':{'repo':{'full_name':'example/accounts'},'ref':'main'},'head':{'repo':{'full_name':'example/accounts'},'sha':'a'*40},
            'body':self.c['task_url'],'number':2,'state':'open','merged':False,'merge_commit_sha':None}

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
        if '/contents/' in path and T.POLICY_PATH not in path:return self.files[path]
        if '/contents/' in path:return {'type':'file','path':T.POLICY_PATH,'size':1000,'sha':('c' if self.policy_drift and path.endswith('d'*40) else 'b')*40,'content':base64.b64encode(json.dumps(self.policy).encode()).decode()}
        if path.startswith('repos/example/config/pulls/'):return self.config_rawpr
        if '/pulls/' in path:return self.rawpr
        if '/git/commits/' in path:return {'tree':{'sha':'b'*40}}
        if '/actions/runs/' in path:return self.rawruns[int(path.split('/')[-1])]
        if '/actions/artifacts/' in path:return self.metadata[int(path.split('/')[-1])]
        if '/comments?' in path:return self.comments
        if '/issues/' in path:
            issue=int(path.split('/')[-1]);repo='/'.join(path.split('/')[1:3]);return {'number':issue,'url':f'https://api.github.com/repos/{repo}/issues/{issue}'}
        raise AssertionError('unexpected API route')

    def decide(self,stage='merge'):
        with patch.object(T.reader,'api',side_effect=self.api):return T.verified(self.c,stage,'f'*40,self.selectors)

    def test_verified_retrieval_never_executes(self):
        r=self.decide();self.assertEqual(r['status'],'VERIFIED_GATE');self.assertFalse(r['dispatch_authorized']);self.assertEqual(r['execution'],'NOT_RUN')

    def test_new_tag_candidate_is_blocked_without_trusted_provenance(self):
        self.c['schema'] = 2
        self.c['sources'][0]['base_sha'] = 'd' * 40
        self.c['feature_tag'] = 'smoke-' + self.c['feature_id']
        self.c['domains']['sit'] = self.c['feature_tag'] + '-sit.' + self.policy['domain_suffix']
        F.bind_fixture_components(self.c, self.policy)
        self.selectors = {'builds': self.selectors['builds']}
        with self.assertRaisesRegex(T.gate.Blocked, 'tag not in reviewed policy'):
            self.decide('sit')

    def test_tagged_rehearsal_requires_tag_main_and_build_evidence(self):
        self.c.update(schema=2, candidate_mode='main-rehearsal', feature_tag='smoke-' + self.c['feature_id'])
        self.c['domains']['sit'] = self.c['feature_tag'] + '-sit.' + self.policy['domain_suffix']
        self.c['sources'][0].update(kind='baseline', pr=None)
        self.c['sources'][0].update(website_content_repository='example/content', website_content_sha='e' * 40)
        self.policy['main_rehearsal_tasks'] = [self.c['task_url']]
        self.policy['feature_sit_frontend_repository'] = 'example/accounts'
        self.policy['website_content_repositories'] = ['example/content']
        self.documents[102].update(website_content_repository='example/content', website_content_sha='e' * 40,
                                   environment='sit', build_mode='feature-sit', candidate_hostname=self.c['domains']['sit'])
        self.archive(102, 'manifest.json', json.dumps(self.documents[102]))
        F.bind_fixture_components(self.c, self.policy)
        self.selectors = {'builds': self.selectors['builds']}
        with patch.object(T.reader, 'api', side_effect=self.api), \
             patch.object(T, 'verify_feature_tag') as tag_check, \
             patch.object(T, 'verify_gitops_domain') as gitops_check, \
             patch.object(T, 'verify_main_rehearsal_sources') as main_check:
            result = T.verified(self.c, 'sit', 'f' * 40, self.selectors)
            self.assertEqual(result['status'], 'VERIFIED_GATE')
            self.assertEqual(result['verified_website_content'], {'repository':'example/content','sha':'e'*40})
            self.assertFalse(result['dispatch_authorized'])
            self.assertEqual(tag_check.call_count, 2)
            self.assertEqual(gitops_check.call_count, 2)
            self.assertEqual(main_check.call_count, 2)
            self.documents[102]['website_content_sha'] = 'b' * 40
            self.archive(102, 'manifest.json', json.dumps(self.documents[102]))
            with self.assertRaisesRegex(T.gate.Blocked, 'frontend SIT build inputs'):
                T.verified(self.c, 'sit', 'f' * 40, self.selectors)
            self.documents[102]['website_content_sha'] = 'e' * 40
            self.archive(102, 'manifest.json', json.dumps(self.documents[102]))
            main_check.side_effect = T.gate.Blocked('Main moved')
            with self.assertRaisesRegex(T.gate.Blocked, 'Main moved'):
                T.verified(self.c, 'sit', 'f' * 40, self.selectors)

    def test_rehearsal_rejects_moved_main(self):
        self.c['candidate_mode'] = 'main-rehearsal'
        self.c['sources'][0].update(kind='baseline', pr=None)
        self.policy['main_rehearsal_tasks'] = [self.c['task_url']]
        with patch.object(T.reader, 'api', return_value={'object': {'type': 'commit', 'sha': 'a' * 40}}):
            T.verify_main_rehearsal_sources(self.c, self.policy)
        with patch.object(T.reader, 'api', return_value={'object': {'type': 'commit', 'sha': 'b' * 40}}):
            with self.assertRaisesRegex(T.gate.Blocked, 'Main moved'):
                T.verify_main_rehearsal_sources(self.c, self.policy)

    def test_reviewed_tag_binding_rejects_moved_tag_and_candidate(self):
        self.c['feature_tag'] = 'smoke-' + self.c['feature_id']
        tag = self.c['feature_tag']
        self.policy['tag_repositories'] = ['example/control']
        self.policy['feature_tags'] = {tag: {'repository': 'example/control', 'tag_object_sha': 'a' * 40,
            'target_sha': 'b' * 40, 'candidate_sha256': T.gate.identity(self.c), 'task_url': self.c['task_url']}}
        def api(path):
            if '/git/ref/tags/' in path:
                return {'ref': 'refs/tags/' + tag, 'object': {'type': 'tag', 'sha': 'a' * 40}}
            if path.endswith('/git/ref/heads/main'):
                return {'object': {'sha': 'c' * 40}}
            if '/compare/' in path:
                return {'status': 'ahead'}
            return {'sha': 'a' * 40, 'tag': tag, 'object': {'type': 'commit', 'sha': 'b' * 40}}
        with patch.object(T.reader, 'api', side_effect=api):
            T.verify_feature_tag(self.c, self.policy)
            self.c['task_url'] += '1'
            with self.assertRaisesRegex(T.gate.Blocked, 'invalid reviewed tag binding'):
                T.verify_feature_tag(self.c, self.policy)
        self.c['task_url'] = self.c['task_url'][:-1]
        def divergent(path):
            return {'status': 'diverged'} if '/compare/' in path else api(path)
        with patch.object(T.reader, 'api', side_effect=divergent):
            with self.assertRaisesRegex(T.gate.Blocked, 'not reachable from Main'):
                T.verify_feature_tag(self.c, self.policy)
        with patch.object(T.reader, 'api', return_value={'ref': 'refs/tags/' + tag, 'object': {'type': 'tag', 'sha': 'c' * 40}}):
            with self.assertRaisesRegex(T.gate.Blocked, 'tag ref moved'):
                T.verify_feature_tag(self.c, self.policy)

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
        loc=self.selectors['acceptance'];loc['attempt']=2
        self.rawruns[42]['run_attempt']=2;self.metadata[101]['name']='acceptance-42-2'
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
                result=F.gate.gate(self.c,stage='merge',policy_commit='f'*40,evidence_selectors=self.selectors)
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
        self.policy['merge_build_owners']={'example/accounts':{k:loc[k] for k in ('repository','workflow','event','filename')}}
        self.policy['merge_build_owners']['example/accounts']['artifact_prefix']='merge'
        self.selectors['merge_builds']={'example/accounts':{k:loc[k] for k in ('run_id','attempt','artifact_id')}}
        self.rawruns[12]=dict(self.rawruns[11],id=12,head_sha='e'*40,event='push')
        proof={'repository':'example/accounts','merge_sha':'e'*40,'source_sha':'a'*40,
               'image':self.c['sources'][0]['image'],'manifest_sha256':'c'*64}
        self.archive(103,'manifest.json',json.dumps(proof));self.metadata[103].update(name=loc['artifact_name'],workflow_run={'id':12})
        self.comment['body']=self.comment['body'].replace('action=merge','action=uat')
        result=self.decide('uat');self.assertEqual(result['namespace'],'web-saas-uat')
        proof['image']='other@sha256:'+'d'*64;self.archive(103,'manifest.json',json.dumps(proof))
        with self.assertRaises(T.gate.Blocked):self.decide('uat')

    def test_second_candidate_new_task_head_and_runs_do_not_change_policy(self):
        policy_before=json.dumps(self.policy,sort_keys=True)
        self.assertEqual(self.decide()['status'],'VERIFIED_GATE')
        source=self.c['sources'][0];source.update(sha='8'*40,pr=3,image='registry.invalid/accounts@sha256:'+'d'*64)
        self.c['task_url']='https://github.com/example/accounts/issues/2'
        self.rawpr['number']=3;self.rawpr['head']['sha']='8'*40;self.rawpr['body']=self.c['task_url']
        self.rawruns[13]=dict(self.rawruns[11],id=13,head_sha='8'*40)
        self.archive(104,'manifest.json',json.dumps({'repository':'example/accounts','source_sha':'8'*40,'image':source['image']}))
        self.metadata[104].update(name='build-13-1',workflow_run={'id':13})
        self.selectors['builds']['example/accounts'].update(run_id=13,artifact_id=104)
        self.rawruns[43]=dict(self.rawruns[42],id=43)
        self.receipt.update(run_id=43,candidate_sha256=T.gate.identity(self.c),image_ids={'example/accounts':source['image']})
        self.archive(105,'receipt.json',json.dumps(self.receipt));self.metadata[105].update(name='acceptance-43-1',workflow_run={'id':43})
        self.selectors['acceptance'].update(run_id=43,artifact_id=105)
        self.comment.update(id=10,issue_url='https://api.github.com/repos/example/accounts/issues/2',
                            html_url=self.c['task_url']+'#issuecomment-10',body='APPROVE feature-candidate '+T.gate.identity(self.c)+' action=merge')
        self.selectors['authorization'].update(issue=2,comment_id=10)
        self.assertEqual(self.decide()['status'],'VERIFIED_GATE')
        self.assertEqual(json.dumps(self.policy,sort_keys=True),policy_before)
        self.rawruns[13]['head_sha']='9'*40
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_selectors_cannot_override_owner_or_embed_evidence(self):
        for name,bad in [('repository','foreign/repo'),('workflow','other.yml'),('filename','other.json'),
                         ('event','push'),('sha','a'*40),('approved',True),('artifact_name','fake')]:
            self.selectors['builds']['example/accounts'][name]=bad
            with self.subTest(name=name),self.assertRaises(T.gate.Blocked):self.decide()
            self.selectors['builds']['example/accounts'].pop(name)
        self.selectors['authorization']['actor']='human'
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_unapproved_task_repo_and_unlinked_pr_are_rejected(self):
        self.c['task_url']='https://github.com/foreign/repo/issues/2'
        with self.assertRaises(T.gate.Blocked):self.decide()
        self.setUp();self.rawpr['body']='unrelated requirement'
        with self.assertRaises(T.gate.Blocked):self.decide()

    def file_record(self,endpoint,path,content):
        self.files[endpoint]={'type':'file','encoding':'base64','path':path,'size':len(content),
                              'content':base64.b64encode(content).decode()}
        return hashlib.sha256(content).hexdigest()

    def refresh_candidate_evidence(self):
        self.receipt['candidate_sha256']=T.gate.identity(self.c)
        self.archive(101,'receipt.json',json.dumps(self.receipt))
        self.comment['body']='APPROVE feature-candidate '+T.gate.identity(self.c)+' action=merge'

    def test_immutable_task_file_works_with_independent_authorization_issue(self):
        path='docs/tasks/referral.md';commit='8'*40
        self.c['task_url']='https://github.com/example/accounts/blob/'+commit+'/'+path
        self.c['task_sha256']=self.file_record('repos/example/accounts/contents/'+path+'?ref='+commit,path,b'original referral requirement')
        self.policy['task_paths']={'example/accounts':['docs/tasks/']}
        self.policy['authorization']['repository']='example/control'
        self.selectors['authorization']['issue']=5
        self.comment.update(issue_url='https://api.github.com/repos/example/control/issues/5',
                            html_url='https://github.com/example/control/issues/5#issuecomment-9')
        self.rawpr['body']=self.c['task_url'];self.refresh_candidate_evidence()
        self.assertEqual(self.decide()['status'],'VERIFIED_GATE')
        self.c['task_sha256']='0'*64
        with self.assertRaises(T.gate.Blocked):self.decide()
        self.c['task_url']=self.c['task_url'].replace(commit,'main')
        with self.assertRaises(T.gate.Blocked):self.decide()

    def test_configuration_only_fix_reuses_verified_baseline_images(self):
        self.c['sources'][0].update(kind='baseline',pr=None)
        self.c['components']={'accounts':{'source_repository':'example/accounts','image':self.c['sources'][0]['image']}}
        self.policy['runtime_components']={'accounts':'example/accounts'}
        self.policy['configuration_paths']={'example/config':['services/referral/']}
        path='services/referral/values.yaml';head='7'*40;base='6'*40
        digest=self.file_record('repos/example/config/contents/'+path+'?ref='+head,path,b'accounts: pinned')
        self.c['configurations']=[{'repository':'example/config','pr':7,'sha':head,'base_ref':'main','base_sha':base,'paths':{path:digest}}]
        self.config_rawpr={'number':7,'head':{'repo':{'full_name':'example/config'},'sha':head},
                           'base':{'repo':{'full_name':'example/config'},'ref':'main','sha':base},
                           'body':self.c['task_url'],'state':'open','merged':False}
        self.receipt['image_ids']={'accounts':self.c['sources'][0]['image']};self.refresh_candidate_evidence()
        self.assertEqual(self.decide()['status'],'VERIFIED_GATE')
        self.config_rawpr.update(state='closed',merged=True,merge_commit_sha='9'*40)
        self.file_record('repos/example/config/contents/'+path+'?ref='+'9'*40,path,b'accounts: pinned')
        self.selectors['merge_builds']={};self.comment['body']=self.comment['body'].replace('action=merge','action=uat')
        self.assertEqual(self.decide('uat')['status'],'VERIFIED_GATE')
        self.file_record('repos/example/config/contents/'+path+'?ref='+'9'*40,path,b'changed config')
        with self.assertRaises(T.gate.Blocked):self.decide('uat')

    def test_wrong_pr_head_or_fork_rejected(self):
        self.rawpr['head']['repo']['full_name']='fork/accounts'
        with self.assertRaises(T.gate.Blocked):self.decide()

if __name__=='__main__':unittest.main()
