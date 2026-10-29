import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('iac_prov',ROOT/'.github/scripts/platform-ops/v6/iac_receipt_provenance.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class Provenance(unittest.TestCase):
    def setUp(self):
        self.run={'id':p.RUN,'run_attempt':1,'repository':{'full_name':p.REPO},'event':'workflow_dispatch',
                  'path':'.github/workflows/iac-orchestrator.yml','head_branch':'v6.0.0-bootstrap.4',
                  'head_sha':p.WORKFLOW_SHA,'status':'completed','conclusion':'success'}
        self.artifact={'id':p.ARTIFACT,'name':p.NAME,'digest':p.ARCHIVE_SHA,'expired':False,
                       'workflow_run':{'id':p.RUN,'head_sha':p.WORKFLOW_SHA}}
        self.summary={'result':'applied_verified','context':{'action':'apply','environment':'prod',
             'gitops_sha':p.GITOPS_SHA,'iac_sha':p.IAC_SHA,'run_id':str(p.RUN),'run_attempt':'1',
             'correlation_id':f'{p.PARENT}:1:prod-k3s-v6','manifest_path':'iac/targets/prod-akamai-k3s-v6.yaml'}}
        self.fetches=[]
    def api(self,path): return self.run if '/runs/' in path else self.artifact
    def fetch(self,*args): self.fetches.append(args);return json.dumps(self.summary).encode()
    def resolve(self):
        digest=hashlib.sha256(json.dumps(self.summary).encode()).hexdigest()
        with patch.object(p,'SUMMARY_SHA',digest):return p.resolve(self.api,self.fetch)
    def test_valid(self):
        _,e=self.resolve();self.assertEqual(e['run_id'],p.RUN);self.assertEqual(len(self.fetches),1)
    def test_bad_provenance_fails_before_download(self):
        for target,key,value in [('run','path','wrong'),('run','conclusion','failure'),('run','head_sha','0'*40),
                                 ('artifact','digest','wrong'),('artifact','expired',True)]:
            with self.subTest(target=target,key=key):
                self.setUp();getattr(self,target)[key]=value
                with self.assertRaises(ValueError):self.resolve()
                self.assertEqual(self.fetches,[])
    def test_wrong_parent_and_target_are_rejected(self):
        for key,value in [('correlation_id','wrong'),('environment','uat'),('iac_sha','0'*40),('action','plan')]:
            with self.subTest(key=key):
                self.setUp();self.summary['context'][key]=value
                with self.assertRaises(ValueError):self.resolve()
    def test_wrong_digest_is_rejected(self):
        with self.assertRaises(ValueError):p.resolve(self.api,self.fetch)

if __name__=='__main__':unittest.main()
