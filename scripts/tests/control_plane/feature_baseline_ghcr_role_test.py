import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]

class BaselineRegistryRoleTest(unittest.TestCase):
    def test_only_exact_workload_and_secret(self):
        role=json.loads((ROOT/'scripts/vault/roles/github-actions-feature-baseline-ghcr-read-sit.json').read_text())
        claims=role['bound_claims']
        self.assertEqual(claims, {'repository':'ai-workspace-infra/playbooks','repository_id':'1120489996',
                                 'repository_owner_id':'292703558','job_workflow_ref':'ai-workspace-infra/playbooks/.github/workflows/feature-baseline-1483.yml@refs/heads/main',
                                 'ref':'refs/heads/main','environment':'dev'})
        self.assertEqual(role['token_policies'],['github-actions-feature-baseline-ghcr-read-sit'])
        self.assertTrue(role['token_no_default_policy'])
        self.assertEqual(role['token_max_ttl'],'10m')
        policy=(ROOT/'scripts/vault/policies/github-actions-feature-baseline-ghcr-read-sit.hcl').read_text()
        self.assertEqual(policy.count('path "'),1)
        self.assertIn('path "kv/data/sit/platform/ghcr/feature-baseline"',policy)
        self.assertIn('capabilities = ["read"]',policy)

if __name__ == '__main__': unittest.main()
