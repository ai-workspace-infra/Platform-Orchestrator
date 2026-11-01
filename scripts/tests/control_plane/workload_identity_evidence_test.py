import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'.github/scripts/platform-ops/identity'
sys.path.insert(0,str(DIR))
spec=importlib.util.spec_from_file_location('evidence',DIR/'verify_workload_identity_evidence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.decl={'environment':'prod','target':{'node':'candidate','kubernetesVersion':'v1.37.1+k3s1',
              'iacTargetManifest':'iac/test.yaml','provider':'test-cloud','account':'test-account',
              'declaration':'resources/test.yaml'},
              'evidence':{'source':'current-run','workflow':'.github/workflows/selfhost-orchestrator.yml'}}
        common={'repository':'example/repo','run_id':12,'attempt':1,'workflow':'.github/workflows/owner.yml',
                'event':'workflow_dispatch','ref':'main','commit':'a'*40,'artifact_id':2,
                'artifact_name':'owner-artifact','artifact_digest':'sha256:'+'e'*64}
        self.resolved=copy.deepcopy(self.decl)
        self.resolved['evidence']={
            'bootstrap':{**common,'filename':'bootstrap.json','file_sha256':'f'*64,'gitopsSha':'b'*40},
            'iac':{**common,'filename':'summary.json','file_sha256':'f'*64,'iacSha':'c'*40,
                   'inventorySha256':'d'*64},
        }
        self.boot={'result':'FLUX_HANDOVER_VERIFIED','node':'candidate','version':'v1.37.1+k3s1','gitops_sha':'b'*40,
                   'common':{'result':'COMMON_NODE_VERIFIED','node':'candidate','cmdb_instance_id':'123',
                             'os_identities':'OS_IDENTITY_CHECKS_PASSED'}}
        self.summary={'result':'applied_verified','context':{'action':'apply','environment':'prod','gitops_sha':'b'*40,
            'iac_sha':'c'*40,'run_id':'12','run_attempt':'1','correlation_id':'11:1:selfhost',
            'manifest_path':'iac/catalog.yaml','declaration_files':{'iac/test.yaml':'hash'},
            'targets':[{'environment':'prod','provider':'test-cloud','account':'test-account',
                'stages':{'resources':{'manifest':'resources/test.yaml'}}}]}}
        self.inventory={'target':{'candidate':{'instance_id':'123'}}}

    def artifact(self,api,fetch,contract,allowed_conclusions=('success',)):
        filename=contract['filename']
        if filename=='bootstrap.json':
            self.assertEqual(set(allowed_conclusions),{'success','failure'})
            return json.dumps(self.boot).encode()
        self.assertEqual(set(allowed_conclusions),{'success'})
        if filename=='summary.json':return json.dumps(self.summary).encode()
        if filename=='inventory.json':return json.dumps(self.inventory).encode()
        raise AssertionError(filename)

    def run_verify(self):
        with patch.object(m,'resolve_current_run',return_value=self.resolved), \
             patch.object(m.provenance,'verify_artifact',side_effect=self.artifact):
            return m.verify(self.decl,parent_run_id='100',repository='example/repo')

    def test_valid_current_run_evidence(self):
        self.assertIn('bootstrap_sha256',self.run_verify())

    def test_rejects_instance_mismatch_and_wrong_environment(self):
        self.inventory['target']['candidate']['instance_id']='999'
        with self.assertRaises(ValueError):self.run_verify()
        self.inventory['target']['candidate']['instance_id']='123'
        self.summary['context']['environment']='uat'
        with self.assertRaises(ValueError):self.run_verify()

    def test_rejects_missing_selected_target_or_bootstrap_identities(self):
        self.summary['context']['declaration_files']={}
        with self.assertRaises(ValueError):self.run_verify()
        self.summary['context']['declaration_files']={'iac/test.yaml':'hash'}
        self.boot['common'].pop('os_identities')
        with self.assertRaises(ValueError):self.run_verify()

    def test_current_run_requires_the_parent_id_and_current_run_declaration(self):
        with patch.object(m,'resolve_current_run',side_effect=ValueError('missing evidence')):
            with self.assertRaises(ValueError):m.verify(self.decl,parent_run_id=None,repository='example/repo')


if __name__=='__main__':unittest.main()
