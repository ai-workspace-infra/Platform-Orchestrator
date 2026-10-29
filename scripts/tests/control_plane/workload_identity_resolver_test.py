import copy
import importlib.util
from pathlib import Path
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('resolve',ROOT/'.github/scripts/platform-ops/identity/resolve_workload_identity.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.d={'apiVersion':'operations.svc.plus/v1alpha1','kind':'VaultWorkloadIdentityOperation','spec':{'environment':'uat',
          'target':{'runtime':'kubernetes','node':'test-node','declaration':'resources/test.yaml','iacTargetManifest':'iac/test.yaml'},
          'vault':{'address':'https://vault.example.com','sshKeyPath':'kv/data/uat/ssh','providerTokenPath':'kv/data/uat/cloud'},
          'identity':{'mount':'jwt-uat','role':'reader','policy':'reader','namespace':'test-ns','serviceAccount':'reader','probeServiceAccount':'probe','audience':'vault-uat','deniedAudience':'vault-denied','allowedPath':'kv/data/uat/cert','deniedPath':'kv/data/uat/other','ttlSeconds':600},
          'evidence':{}}}
        common={'runId':1,'attempt':1,'artifactId':1,'commit':'a'*40,'artifactDigest':'sha256:'+'b'*64,'fileSha256':'c'*64}
        self.d['spec']['evidence']={'bootstrap':{**common,'gitopsSha':'d'*40},'iac':{**common,'iacSha':'e'*40,'inventorySha256':'f'*64}}
    def test_generic_target_and_separate_environment(self):
        self.assertEqual(m.validate(self.d)['target']['runtime'],'kubernetes')
    def test_rejects_scope_escape_and_ambiguous_denial(self):
        for group,key,value in [('target','declaration','../outside.yaml'),('identity','allowedPath','kv/data/*'),('identity','deniedPath','kv/data/uat/cert'),('vault','address','http://vault.example.com')]:
            with self.subTest(group=group,key=key):
                d=copy.deepcopy(self.d);d['spec'][group][key]=value
                with self.assertRaises(m.ContractError):m.validate(d)

if __name__=='__main__':unittest.main()
