import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('provenance',ROOT/'.github/scripts/platform-ops/v6/bootstrap_receipt_provenance.py')
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)

class Provenance(unittest.TestCase):
    def setUp(self):
        self.run={'id':p.RUN_ID,'run_attempt':1,'repository':{'full_name':p.REPO},'event':'workflow_dispatch',
                  'path':'.github/workflows/selfhost-orchestrator.yml','head_branch':p.TAG,'head_sha':p.WORKFLOW_SHA,
                  'status':'completed','conclusion':'success'}
        self.artifact={'id':p.ARTIFACT_ID,'name':p.ARTIFACT_NAME,'digest':p.ARTIFACT_DIGEST,'expired':False,
                       'workflow_run':{'id':p.RUN_ID,'head_sha':p.WORKFLOW_SHA}}
        self.tag={'sha':p.WORKFLOW_SHA}
        self.raw=json.dumps({'result':'PAUSED_BOOTSTRAP_VERIFIED','node':'prod-k3s-v6','version':'v1.37.1+k3s1',
                 'gitops_sha':p.GITOPS_SHA,'common':{'result':'COMMON_NODE_VERIFIED','node':'prod-k3s-v6'},
                 'audit':{'result':'AUDIT_ALLOW_DENY_VERIFIED'},'node_uid':'12345678-1234-1234-1234-123456789abc',
                 'cluster_uid':'abcdef01-1234-1234-1234-123456789abc'}).encode()
        self.fetches=[]
    def api(self,path):
        if '/actions/runs/' in path: return self.run
        if '/actions/artifacts/' in path: return self.artifact
        return self.tag
    def fetch(self,*args): self.fetches.append(args); return self.raw
    def resolve(self):
        with patch.object(p,'RECEIPT_SHA256',hashlib.sha256(self.raw).hexdigest()): return p.resolve(self.api,self.fetch)
    def test_valid_provenance_returns_bound_receipt(self):
        raw, evidence=self.resolve(); self.assertEqual(raw,self.raw); self.assertEqual(evidence['run_id'],p.RUN_ID); self.assertEqual(len(self.fetches),1)
    def test_rejects_wrong_run_before_artifact_download(self):
        for key,value in [('event','push'),('path','other'),('head_sha','0'*40),('head_branch','main'),('conclusion','failure'),('run_attempt',2)]:
            with self.subTest(key=key):
                self.setUp();self.run[key]=value
                with self.assertRaises(ValueError): self.resolve()
                self.assertEqual(self.fetches,[])
    def test_rejects_changed_tag_or_artifact(self):
        for target,key,value in [('tag','sha','0'*40),('artifact','digest','sha256:'+'0'*64),('artifact','expired',True)]:
            with self.subTest(target=target,key=key):
                self.setUp();getattr(self,target)[key]=value
                with self.assertRaises(ValueError): self.resolve()
                self.assertEqual(self.fetches,[])
    def test_rejects_wrong_receipt_digest(self):
        with self.assertRaises(ValueError): p.resolve(self.api,self.fetch)

if __name__=='__main__': unittest.main()
