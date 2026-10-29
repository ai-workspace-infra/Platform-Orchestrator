"""Contract coverage for any candidate declaration supplied by the test runner."""
import importlib.util
import os
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('identity_resolver',ROOT/'.github/scripts/platform-ops/identity/resolve_workload_identity.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class DeclarationIntegration(unittest.TestCase):
    def test_candidate_declaration_matches_real_owner_schema(self):
        checkout=os.environ.get('WORKLOAD_IDENTITY_TEST_CHECKOUT')
        if not checkout:self.skipTest('candidate checkout not supplied')
        operation=os.environ['WORKLOAD_IDENTITY_TEST_OPERATION']
        config=r.load(checkout,operation)
        owner_path=Path(os.environ['WORKLOAD_IDENTITY_TEST_OWNER'])
        import sys
        sys.path.insert(0,str(owner_path/'roles/vhosts/vault_jwt_workload_identity/files'))
        from vault_contract import IdentitySpec
        mapping={'serviceAccount':'service_account','deniedAudience':'denied_audience','probeServiceAccount':'probe_service_account',
                 'allowedPath':'allowed_path','deniedPath':'denied_path','ttlSeconds':'ttl_seconds'}
        identity=IdentitySpec(**{mapping.get(k,k):v for k,v in config['identity'].items()})
        self.assertNotEqual(identity.subject,identity.probe_subject)
        self.assertNotEqual(identity.allowed_path,identity.denied_path)

if __name__=='__main__':unittest.main()
