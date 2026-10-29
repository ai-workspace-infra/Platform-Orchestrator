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
        self.data={'bootstrap':b'b','summary':b's','inventory':b'i','bootstrap_sha256':hashlib.sha256(b'b').hexdigest(),'summary_sha256':hashlib.sha256(b's').hexdigest()}
        self.config={'environment':'uat','target':{'provider':'provider','account':'account','node':'node','iacTargetManifest':'iac/x.yaml'},
             'vault':{'address':'https://vault.example','accessRole':'access','adminRole':'admin','sshKeyPath':'kv/data/ssh','sshKeyField':'SSH_PRIVATE_KEY','providerTokenPath':'kv/data/cloud','providerTokenField':'TOKEN'},
             'evidence':{'bootstrap':{'gitopsSha':'a'*40},'iac':{'iacSha':'b'*40,'runId':1,'attempt':1,'correlationId':'1:1:node'}}}
    def test_materializes_only_verified_receipts(self):
        from unittest.mock import patch
        with patch.object(m.resolver,'load',return_value=self.config):
            result=m.prepare(self.root,'candidate.yaml',self.sha,self.out,lambda spec:self.data)
        self.assertEqual((Path(result['directory'])/'inventory.json').read_bytes(),b'i')
        self.assertEqual((Path(result['directory'])/'bootstrap.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(result['environment'],'uat')
    def test_dirty_or_wrong_checkout_stops_before_fetch(self):
        calls=[];(self.root/'candidate.yaml').write_text('changed')
        with self.assertRaises(ValueError):m.prepare(self.root,'candidate.yaml',self.sha,self.out,lambda spec:calls.append(spec))
        self.assertEqual(calls,[])
        self.assertEqual(list(self.out.iterdir()),[])

if __name__=='__main__':unittest.main()
