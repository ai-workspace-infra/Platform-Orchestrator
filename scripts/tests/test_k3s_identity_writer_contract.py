"""Validate the precise issuance-only Vault identity contract."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
NAME = 'github-actions-platform-ops-toolkit-prod-k3s-v6-identity-writer'


class Contract(unittest.TestCase):
    def test_policy_has_only_three_exact_create_read_paths(self):
        policy = (ROOT / 'scripts/vault/policies' / (NAME + '.hcl')).read_text()
        rules = re.findall(r'path "([^"]+)"\s*\{\s*capabilities\s*=\s*(\[[^\]]+\])\s*\}', policy)
        self.assertEqual({p for p, _ in rules}, {'kv/data/prod/prod-k3s-v6/' + r for r in ('root', 'operator', 'auditor')})
        self.assertEqual(len(rules), 3)
        for path, caps in rules:
            self.assertNotIn('*', path)
            self.assertEqual(set(json.loads(caps)), {'create', 'read'})

    def test_oidc_binding_is_protected_production_workflow_only(self):
        role = json.loads((ROOT / 'scripts/vault/roles' / (NAME + '.json')).read_text())
        self.assertEqual(role['token_policies'], [NAME])
        self.assertTrue(role['token_no_default_policy'])
        self.assertEqual(role['bound_audiences'], ['vault'])
        claims = role['bound_claims']
        self.assertEqual(claims['repository'], 'ai-workspace-infra/Platform-Orchestrator')
        self.assertEqual(claims['environment'], 'prod')
        self.assertEqual(claims['ref_protected'], 'true')
        self.assertEqual(claims['ref'], ['refs/heads/main'])
        self.assertEqual(claims['workflow_ref'], 'ai-workspace-infra/Platform-Orchestrator/.github/workflows/selfhost-orchestrator.yml@refs/heads/main')
        self.assertEqual(role['token_explicit_max_ttl'], '10m')


if __name__ == '__main__':
    unittest.main()
