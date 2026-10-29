import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'.github/scripts/platform-ops/identity'
sys.path.insert(0,str(DIR))
spec=importlib.util.spec_from_file_location('evidence',DIR/'verify_workload_identity_evidence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.decl={'environment':'uat','target':{'node':'candidate','kubernetesVersion':'v1.33.4','iacTargetManifest':'iac/test.yaml'},
          'evidence':{'bootstrap':{'repository':'example/repo','ref':'v1','commit':'a'*40,'gitopsSha':'b'*40},
                      'iac':{'repository':'example/repo','ref':'v1','commit':'a'*40,'iacSha':'c'*40,'runId':1,'attempt':1,'correlationId':'1:1:candidate','inventorySha256':'d'*64}}}
        common={'runId':1,'attempt':1,'workflow':'workflow','event':'workflow_dispatch','artifactId':1,'artifactName':'artifact','artifactDigest':'sha256:'+'e'*64,'filename':'receipt','fileSha256':'f'*64}
        for row in self.decl['evidence'].values():row.update(common)
        self.boot={'result':'PAUSED_BOOTSTRAP_VERIFIED','node':'candidate','version':'v1.33.4','gitops_sha':'b'*40,
                   'common':{'result':'COMMON_NODE_VERIFIED','node':'candidate','cmdb_instance_id':'123'},'audit':{'result':'AUDIT_ALLOW_DENY_VERIFIED'}}
        self.summary={'result':'applied_verified','context':{'action':'apply','environment':'uat','gitops_sha':'b'*40,'iac_sha':'c'*40,'run_id':'1','run_attempt':'1','correlation_id':'1:1:candidate','manifest_path':'iac/test.yaml'}}
        self.inventory={'target':{'candidate':{'instance_id':'123'}}}
    def fake(self,api,fetch,contract):
        if contract['filename']=='inventory.json':return json.dumps(self.inventory).encode()
        if contract['commit']=='a'*40 and contract['file_sha256']=='f'*64:
            if self.count==0:self.count+=1;return json.dumps(self.boot).encode()
            return json.dumps(self.summary).encode()
        raise AssertionError()
    def run_verify(self):
        self.count=0
        with patch.object(m.provenance,'verify_artifact',side_effect=self.fake):
            return m.verify(self.decl,lambda path:{'sha':'a'*40},lambda *args:None)
    def test_valid_generic_target(self):self.assertIn('bootstrap_sha256',self.run_verify())
    def test_rejects_instance_mismatch_and_wrong_environment(self):
        self.inventory['target']['candidate']['instance_id']='999'
        with self.assertRaises(ValueError):self.run_verify()
        self.inventory['target']['candidate']['instance_id']='123';self.summary['context']['environment']='prod'
        with self.assertRaises(ValueError):self.run_verify()
    def test_rejects_tag_drift_before_fetch(self):
        with patch.object(m.provenance,'verify_artifact') as f:
            with self.assertRaises(ValueError):m.verify(self.decl,lambda path:{'sha':'0'*40},lambda *a:None)
            f.assert_not_called()

if __name__=='__main__':unittest.main()
