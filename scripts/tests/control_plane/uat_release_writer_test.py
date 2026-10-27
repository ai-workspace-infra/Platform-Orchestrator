import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import types
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[3]
p=ROOT/'.github/scripts/feature-lane/uat_release.py'
spec=importlib.util.spec_from_file_location('uat_release',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BASE='a'*40;SOURCE='b'*40;OLD='c'*40;DIGEST='sha256:'+'d'*64


def release():
    values={}
    for key,repo in m.REPOS.items():
        value={'podAnnotations':{m.PREFIX+'source_repository':repo,m.PREFIX+'source_sha':OLD,
               m.PREFIX+'image_digest':DIGEST,m.PREFIX+'build_run_id':'10'}}
        image=m.IMAGES[key]+'@'+DIGEST
        if key in ('caddy','postgresql'):value['image']=image
        elif key=='console':value['singleContainer']={'image':image}
        else:value['workload']={'image':image,'env':{'IMAGE':image}}
        values[key]=value
    return values


class Trusted:
    def __init__(self):
        self.reader=types.SimpleNamespace(api=self.api);self.calls=[];self.artifacts=[];self.current=SOURCE;self.base=BASE
        self.run={'head_branch':'main','head_sha':SOURCE,'event':'push','path':'.github/workflows/ci-pipeline.yml',
                  'repository':{'full_name':m.REPOS['accounts']},'head_repository':{'full_name':m.REPOS['accounts']},
                  'status':'completed','conclusion':'success','run_attempt':2}
        self.proof={'schema':'main-image-build/v1','source_repository':m.REPOS['accounts'],'source_sha':SOURCE,
                    'event':'push','ref':'refs/heads/main','run_id':12,'attempt':2,'platform':'linux/amd64',
                    'image':m.IMAGES['accounts']+'@sha256:'+'e'*64}
    def api(self,path):
        self.calls.append(path)
        if path==f'repos/{m.GITOPS}/branches/main':return {'commit':{'sha':self.base},'protected':True}
        if path==f'repos/{m.REPOS["accounts"]}/branches/main':return {'commit':{'sha':self.current}}
        if '/actions/runs/' in path:return self.run
        if '/contents/' in path:
            raw=yaml.safe_dump(release(),sort_keys=False).encode()
            return {'type':'file','path':m.RELEASE_PATH,'encoding':'base64','size':len(raw),'content':base64.b64encode(raw).decode()}
        if '/git/commits/' in path:return {'tree':{'sha':'f'*40}}
        raise AssertionError(path)
    def artifact(self,locator):
        self.artifacts.append(locator)
        return self.proof,{'document_sha256':hashlib.sha256(json.dumps(self.proof).encode()).hexdigest()}


class UATWriter(unittest.TestCase):
    def test_verified_main_build_changes_only_accounts_and_complete_fingerprint(self):
        t=Trusted();plan=m.prepare(t,BASE,12,2,34);doc=yaml.safe_load(plan['content']);old=release()
        self.assertEqual(doc['accounts']['workload']['image'],t.proof['image'])
        self.assertEqual(doc['accounts']['workload']['env']['IMAGE'],t.proof['image'])
        for key in m.REPOS:
            if key!='accounts':self.assertEqual(doc[key],old[key])
        expected=hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(plan['matrix_fingerprint'],expected)
        self.assertEqual(t.artifacts[0]['artifact_name'],'accounts-main-image-12-2')
        self.assertEqual(t.artifacts[0]['filename'],'main-image-build.json')

    def test_non_main_failed_fork_or_stale_source_refused_before_artifact(self):
        changes=({'head_branch':'daily-build-2026.10.25'},{'event':'workflow_dispatch'},{'conclusion':'failure'},
                 {'head_sha':OLD},{'head_repository':{'full_name':'fork/accounts'}},{'path':'.github/workflows/foreign.yml'},{'run_attempt':1})
        for change in changes:
            with self.subTest(change=change):
                t=Trusted();t.run.update(change)
                self.assertRaises(m.Blocked,m.prepare,t,BASE,12,2,34);self.assertFalse(t.artifacts)
        t=Trusted();self.assertRaises(m.Blocked,m.prepare,t,OLD,12,2,34)

    def test_mismatched_manifest_and_mutable_image_are_refused(self):
        for change in ({'source_sha':OLD},{'run_id':99},{'attempt':1},{'source_repository':'fork/accounts'},
                       {'image':m.IMAGES['accounts']+':latest'},{'image_refs':[m.IMAGES['accounts']+':sha-'+SOURCE],'image':None}):
            t=Trusted();t.proof.update(change)
            self.assertRaises(m.Blocked,m.prepare,t,BASE,12,2,34)

    def test_unsupported_baselines_and_image_environment_drift_refused(self):
        for mutate in (lambda d:d.pop('postgresql'),lambda d:d['billing']['workload']['env'].update(IMAGE='wrong'),
                       lambda d:d['caddy']['podAnnotations'].update({m.PREFIX+'source_repository':'other/repo'})):
            d=release();mutate(d);self.assertRaises((m.Blocked,KeyError),m.update_release,d,Trusted().proof)

    def test_main_race_during_artifact_fetch_refused(self):
        t=Trusted();original=t.artifact
        def artifact(locator):
            value=original(locator);t.current=OLD;return value
        t.artifact=artifact
        self.assertRaises(m.Blocked,m.prepare,t,BASE,12,2,34)

    def test_publication_creates_only_fixed_file_feature_ref_and_draft_pr(self):
        t=Trusted();plan=m.prepare(t,BASE,12,2,34);calls=[]
        def mutate(path,payload):
            calls.append((path,payload));return {'sha':'f'*40,'html_url':'https://github.com/'+m.GITOPS+'/pull/999'}
        result=m.publish(t,plan,mutate)
        self.assertIn('/pull/999',result['html_url'])
        self.assertEqual(calls[1][1]['tree'][0]['path'],m.RELEASE_PATH)
        self.assertEqual(len(calls[1][1]['tree']),1)
        self.assertTrue(calls[3][1]['ref'].startswith('refs/heads/feature/dev-uat-accounts-'))
        self.assertEqual(calls[4][1]['base'],'main');self.assertTrue(calls[4][1]['draft'])
        self.assertFalse(any(payload.get('ref')=='refs/heads/main' for _,payload in calls))

    def test_main_advance_after_branch_creation_prevents_pr(self):
        t=Trusted();plan=m.prepare(t,BASE,12,2,34);calls=[]
        def mutate(path,payload):
            calls.append(path)
            if path.endswith('/git/refs'):t.current=OLD
            return {'sha':'f'*40}
        self.assertRaises(m.Blocked,m.publish,t,plan,mutate)
        self.assertFalse(any(path.endswith('/pulls') for path in calls))

    def test_fabricated_or_stale_proposal_cannot_mutate(self):
        t=Trusted();plan=m.prepare(t,BASE,12,2,34);plan['content']='fabricated'
        self.assertRaises(m.Blocked,m.publish,t,plan,lambda *args:self.fail('no mutation'))

if __name__=='__main__':unittest.main()
