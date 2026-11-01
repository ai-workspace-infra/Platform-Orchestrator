import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'.github/scripts/platform-ops/identity';sys.path.insert(0,str(DIR))
s=importlib.util.spec_from_file_location('prepare',DIR/'prepare_workload_identity.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class Prepare(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'repo';self.root.mkdir();self.out=Path(self.tmp.name)/'out';self.out.mkdir()
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        subprocess.run(['git','-C',str(self.root),'config','user.email','test@example.invalid'],check=True)
        subprocess.run(['git','-C',str(self.root),'config','user.name','Test'],check=True)
        (self.root/'candidate.yaml').write_text('candidate')
        subprocess.run(['git','-C',str(self.root),'add','candidate.yaml'],check=True)
        subprocess.run(['git','-C',str(self.root),'commit','-qm','candidate'],check=True)
        self.sha=subprocess.check_output(['git','-C',str(self.root),'rev-parse','HEAD'],text=True).strip()
        bootstrap=json.dumps({'gitops_sha':'a'*40}).encode()
        summary=json.dumps({'context':{'iac_sha':'b'*40,'run_id':456,'run_attempt':2,'correlation_id':'123:1:node'}}).encode()
        self.data={'bootstrap':bootstrap,'summary':summary,'inventory':b'i','iac_catalog_manifest':'iac/catalog.yaml','bootstrap_sha256':hashlib.sha256(bootstrap).hexdigest(),'summary_sha256':hashlib.sha256(summary).hexdigest()}
        self.config={'environment':'uat','target':{'provider':'provider','account':'account','node':'node','iacTargetManifest':'iac/x.yaml'},
             'vault':{'address':'https://vault.example','accessRole':'access','adminRole':'admin','sshKeyPath':'kv/data/ssh','sshKeyField':'SSH_PRIVATE_KEY','providerTokenPath':'kv/data/cloud','providerTokenField':'TOKEN'},
             'evidence':{'source':'current-run','workflow':'.github/workflows/selfhost-orchestrator.yml'}}
    def test_materializes_only_verified_receipts(self):
        from unittest.mock import patch
        with patch.object(m.resolver,'load',return_value=self.config):
            result=m.prepare(self.root,'candidate.yaml',self.sha,self.out,'123','example/repo',lambda spec,**kwargs:self.data)
        self.assertEqual((Path(result['directory'])/'inventory.json').read_bytes(),b'i')
        self.assertEqual((Path(result['directory'])/'bootstrap.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(result['environment'],'uat')
        self.assertEqual(result['bootstrap_gitops_sha'],'a'*40)
        self.assertEqual(result['iac_sha'],'b'*40)
        self.assertEqual(result['iac_run_id'],'456')
        self.assertEqual(result['iac_attempt'],'2')
        self.assertEqual(result['iac_correlation_id'],'123:1:node')
    def test_dirty_or_wrong_checkout_stops_before_fetch(self):
        calls=[];(self.root/'candidate.yaml').write_text('changed')
        with self.assertRaises(ValueError):m.prepare(self.root,'candidate.yaml',self.sha,self.out,'123','example/repo',lambda spec,**kwargs:calls.append(spec))
        self.assertEqual(calls,[])
        self.assertEqual(list(self.out.iterdir()),[])

if __name__=='__main__':unittest.main()
