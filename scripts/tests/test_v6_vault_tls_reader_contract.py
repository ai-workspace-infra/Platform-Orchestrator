"""Validate the narrow workload identity contract independently of Vault."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
NAME = "prod-k3s-v6-vault-tls-reader"


class V6VaultTLSReaderContract(unittest.TestCase):
    def test_role_is_bound_to_one_service_account_and_audience(self):
        role = json.loads((ROOT / "scripts/vault/workload-identities" / (NAME + ".json")).read_text())
        self.assertEqual(role["role_type"], "jwt")
        self.assertEqual(role["user_claim"], "sub")
        self.assertEqual(role["bound_subject"], "system:serviceaccount:vault-prod:vault-tls-reader")
        self.assertEqual(role["bound_audiences"], ["vault-prod-k3s-v6-eso"])
        self.assertEqual(role["token_policies"], [NAME])
        self.assertTrue(role["token_no_default_policy"])
        self.assertEqual(role["token_type"], "batch")
        self.assertEqual(role["token_explicit_max_ttl"], "10m")

    def test_policy_grants_only_the_single_certificate_record(self):
        policy = (ROOT / "scripts/vault/policies" / (NAME + ".hcl")).read_text()
        self.assertEqual(policy.strip(), 'path "kv/data/CICD/domains/svc.plus" {\n  capabilities = ["read"]\n}')


class V6VaultTLSAdminContract(unittest.TestCase):
    def test_role_is_limited_to_protected_v6_identity_workflow(self):
        name = 'github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-admin'
        role = json.loads((ROOT / 'scripts/vault/roles' / (name + '.json')).read_text())
        self.assertEqual(role['token_policies'], [name])
        self.assertTrue(role['token_no_default_policy'])
        self.assertEqual(role['token_explicit_max_ttl'], '20m')
        claims = role['bound_claims']
        self.assertEqual(claims['environment'], 'prod')
        self.assertEqual(claims['ref_protected'], 'true')
        self.assertEqual(claims['ref'], ['refs/tags/v6.*'])
        self.assertEqual(claims['workflow_ref'], 'ai-workspace-infra/Platform-Orchestrator/.github/workflows/vault-workload-identity.yml@refs/tags/v6.*')

    def test_policy_cannot_read_secrets_or_touch_other_auth_mounts(self):
        name = 'github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-admin'
        policy = (ROOT / 'scripts/vault/policies' / (name + '.hcl')).read_text()
        import re
        paths = re.findall(r'^path "([^"]+)"', policy, re.MULTILINE)
        self.assertEqual(set(paths), {'sys/auth', 'sys/auth/jwt-prod-k3s-v6',
            'sys/capabilities-self',
            'sys/policies/acl/prod-k3s-v6-vault-tls-reader', 'auth/jwt-prod-k3s-v6/config',
            'auth/jwt-prod-k3s-v6/role/prod-k3s-v6-vault-tls-reader', 'auth/token/lookup-self'})
        self.assertTrue(all('*' not in path and not path.startswith('kv/') for path in paths))


class V6VaultTLSAccessContract(unittest.TestCase):
    def test_access_is_bound_to_identity_workflow_and_two_records(self):
        import re
        name = 'github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-access'
        role = json.loads((ROOT / 'scripts/vault/roles' / (name + '.json')).read_text())
        self.assertEqual(role['token_policies'], [name])
        self.assertEqual(role['bound_claims']['environment'], 'prod')
        self.assertEqual(role['bound_claims']['ref'], ['refs/tags/v6.*'])
        self.assertEqual(role['bound_claims']['ref_protected'], 'true')
        self.assertEqual(role['bound_claims']['workflow_ref'], 'ai-workspace-infra/Platform-Orchestrator/.github/workflows/vault-workload-identity.yml@refs/tags/v6.*')
        self.assertTrue(role['token_no_default_policy'])
        self.assertEqual(role['token_explicit_max_ttl'], '20m')
        policy=(ROOT / 'scripts/vault/policies' / (name + '.hcl')).read_text()
        self.assertEqual(set(re.findall(r'^path "([^"]+)"',policy,re.MULTILINE)),
            {'kv/data/prod/platform/prod-k3s-v6/ssh', 'kv/data/CICD/prod/akamai-cloud/manbuzhe2026'})
        self.assertEqual(policy.count('capabilities = ["read"]'), 2)


class V6VaultOIDCProvisioningContract(unittest.TestCase):
    def test_bootstrap_oidc_roles_match_the_existing_role_installer_schema(self):
        for name in (
            'github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-admin',
            'github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-access',
        ):
            role = json.loads((ROOT / 'scripts/vault/roles' / f'{name}.json').read_text())
            self.assertEqual(role['role_name'], name)
            self.assertTrue(role['description'])
            self.assertEqual(role['role_type'], 'jwt')
            self.assertEqual(role['user_claim'], 'sub')
            self.assertIsInstance(role['bound_claims'], dict)
            self.assertIsInstance(role['token_policies'], list)
            self.assertTrue(role['token_no_default_policy'])
            self.assertEqual(role['token_type'], 'batch')
            self.assertIsInstance(role['token_ttl'], str)
            self.assertIsInstance(role['token_max_ttl'], str)
            self.assertIsInstance(role['token_explicit_max_ttl'], str)
        self.assertTrue((ROOT / 'scripts/vault/workload-identities' / (NAME + '.json')).is_file())


if __name__ == "__main__":
    unittest.main()
