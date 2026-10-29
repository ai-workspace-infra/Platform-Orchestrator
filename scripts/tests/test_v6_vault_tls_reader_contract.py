"""Validate the narrow workload identity contract independently of Vault."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
NAME = "prod-k3s-v6-vault-tls-reader"


class V6VaultTLSReaderContract(unittest.TestCase):
    def test_role_is_bound_to_one_service_account_and_audience(self):
        role = json.loads((ROOT / "scripts/vault/roles" / (NAME + ".json")).read_text())
        self.assertEqual(role["role_type"], "jwt")
        self.assertEqual(role["user_claim"], "sub")
        self.assertEqual(role["bound_subject"], "system:serviceaccount:vault-prod:vault-tls-reader")
        self.assertEqual(role["bound_audiences"], ["vault-prod-k3s-v6-eso"])
        self.assertEqual(role["token_policies"], [NAME])
        self.assertTrue(role["token_no_default_policy"])
        self.assertEqual(role["token_type"], "batch")
        self.assertLessEqual(role["token_explicit_max_ttl"], 600)

    def test_policy_grants_only_the_single_certificate_record(self):
        policy = (ROOT / "scripts/vault/policies" / (NAME + ".hcl")).read_text()
        self.assertEqual(policy.strip(), 'path "kv/data/CICD/domains/svc.plus" {\n  capabilities = ["read"]\n}')


if __name__ == "__main__":
    unittest.main()
