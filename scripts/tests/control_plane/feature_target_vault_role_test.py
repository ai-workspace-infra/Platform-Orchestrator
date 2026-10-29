import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]

class FeatureTargetRoleTest(unittest.TestCase):
    def test_caller_and_pinned_owner_are_both_required(self):
        role=json.loads((ROOT/'scripts/vault/roles/github-actions-feature-target-read-sit.json').read_text())
        self.assertEqual(role['bound_claims'],{
            'repository':'ai-workspace-infra/Platform-Orchestrator','repository_id':'1284966060',
            'repository_owner_id':'292703558',
            'workflow_ref':'ai-workspace-infra/Platform-Orchestrator/.github/workflows/feature-lane-deploy.yml@refs/heads/main',
            'job_workflow_ref':'ai-workspace-infra/iac_modules/.github/workflows/feature-sit-target-observe.yml@61f79c73d1c415755989fa55c8a36a3b862b391d',
            'ref':'refs/heads/main','environment':'dev'})
        self.assertEqual(role['token_policies'],['github-actions-feature-target-read-sit'])
        self.assertTrue(role['token_no_default_policy'])
        self.assertEqual(role['token_max_ttl'],'10m')
        policy=(ROOT/'scripts/vault/policies/github-actions-feature-target-read-sit.hcl').read_text()
        self.assertEqual(policy.count('path "'),1)
        self.assertIn('path "kv/data/sit/platform/akamai/feature-target"',policy)
        self.assertIn('capabilities = ["read"]',policy)

if __name__ == '__main__': unittest.main()
