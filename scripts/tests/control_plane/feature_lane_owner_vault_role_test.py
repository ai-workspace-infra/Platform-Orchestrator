import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
class OwnerRoleTest(unittest.TestCase):
 def test_exact_pinned_owner_and_two_readonly_paths(self):
  role=json.loads((ROOT/'scripts/vault/roles/github-actions-playbooks-feature-lane-sit.json').read_text())
  self.assertEqual(role['token_policies'],['github-actions-playbooks-feature-lane-sit'])
  self.assertTrue(role['token_no_default_policy']);self.assertEqual(role['token_ttl'],'10m');self.assertEqual(role['token_max_ttl'],'10m')
  c=role['bound_claims'];self.assertEqual(c['environment'],'dev');self.assertEqual(c['ref'],'refs/heads/main')
  self.assertEqual(c['workflow_ref'],'ai-workspace-infra/Platform-Orchestrator/.github/workflows/feature-lane-deploy.yml@refs/heads/main')
  self.assertEqual(c['job_workflow_ref'],'ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@ba3795979eb5bb283ad8b79361d1c09c850288f2')
  policy=(ROOT/'scripts/vault/policies/github-actions-playbooks-feature-lane-sit.hcl').read_text()
  self.assertEqual(policy.count('path '),2);self.assertIn('kv/data/CICD/dev/k3s-bootstrap',policy);self.assertIn('kv/data/sit/platform/ghcr/feature-registry',policy);self.assertNotIn('kv/data/CICD/dev/ghcr',policy)
if __name__=='__main__':unittest.main()
