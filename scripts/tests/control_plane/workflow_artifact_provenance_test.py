import hashlib
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('provenance',ROOT/'.github/scripts/platform-ops/evidence/workflow_artifact_provenance.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Provenance(unittest.TestCase):
    def sample(self,repo,run_id):
        data=b'example'; s={'repository':repo,'run_id':run_id,'attempt':1,'workflow':'.github/workflows/owner.yml','event':'workflow_dispatch','ref':'v2.0.0','commit':'a'*40,'artifact_id':7,'artifact_name':'evidence','artifact_digest':'sha256:'+'b'*64,'filename':'receipt.json','file_sha256':hashlib.sha256(data).hexdigest()}
        run={'id':run_id,'run_attempt':1,'repository':{'full_name':repo},'event':s['event'],'path':s['workflow'],'head_branch':s['ref'],'head_sha':s['commit'],'status':'completed','conclusion':'success'}
        artifact={'id':7,'name':'evidence','digest':s['artifact_digest'],'expired':False,'workflow_run':{'id':run_id,'head_sha':s['commit']}}
        return s,run,artifact,data
    def test_supports_independent_repositories_and_runs(self):
        for repo,run_id in [('example/one',1),('another/two',2)]:
            s,run,artifact,data=self.sample(repo,run_id)
            self.assertEqual(m.verify_artifact(lambda p:run if '/runs/' in p else artifact,lambda *a:data,s),data)
    def test_rejects_mismatched_run_and_digest(self):
        s,run,artifact,data=self.sample('example/one',1);run['conclusion']='failure'
        with self.assertRaises(ValueError):m.verify_artifact(lambda p:run if '/runs/' in p else artifact,lambda *a:data,s)
        run['conclusion']='success'
        with self.assertRaises(ValueError):m.verify_artifact(lambda p:run if '/runs/' in p else artifact,lambda *a:b'tampered',s)

if __name__=='__main__':unittest.main()
