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
  self.assertEqual(set(c['job_workflow_ref']),{'ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@7f57ff7e52beeece5931b1b4122efacbac6de8a1','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@32bcb683d7bfb79e0c01587426252f3f0d8c76a2','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@ad2cf2a32d5faacbc2a327809c9d91dc8412c910','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@4562a6e7804999ac482b0dc399c092d75690a283','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@a30b238424bf6d77eaa9002656d771a3b72ee64f','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@ea5050e9ecc93cef21d8671464d6f495f507227e'})
  policy=(ROOT/'scripts/vault/policies/github-actions-playbooks-feature-lane-sit.hcl').read_text()
  self.assertEqual(policy.count('path '),2);self.assertIn('kv/data/CICD/dev/k3s-bootstrap',policy);self.assertIn('kv/data/sit/platform/ghcr/feature-registry',policy);self.assertNotIn('kv/data/CICD/dev/ghcr',policy)
 def test_seed_has_exact_pinned_workflow_and_one_readonly_path(self):
  role=json.loads((ROOT/'scripts/vault/roles/github-actions-playbooks-feature-seed-sit.json').read_text())
  self.assertEqual(role['bound_claims_type'],'string');self.assertTrue(role['token_no_default_policy'])
  self.assertEqual(set(role['bound_claims']['job_workflow_ref']),{'ai-workspace-infra/playbooks/.github/workflows/dev-web-saas-seed.yml@32bcb683d7bfb79e0c01587426252f3f0d8c76a2','ai-workspace-infra/playbooks/.github/workflows/dev-web-saas-seed.yml@ad2cf2a32d5faacbc2a327809c9d91dc8412c910','ai-workspace-infra/playbooks/.github/workflows/dev-web-saas-seed.yml@4562a6e7804999ac482b0dc399c092d75690a283','ai-workspace-infra/playbooks/.github/workflows/dev-web-saas-seed.yml@a30b238424bf6d77eaa9002656d771a3b72ee64f','ai-workspace-infra/playbooks/.github/workflows/dev-web-saas-seed.yml@ea5050e9ecc93cef21d8671464d6f495f507227e'})
  self.assertEqual(role['bound_claims']['workflow_ref'],'ai-workspace-infra/Platform-Orchestrator/.github/workflows/feature-lane-deploy.yml@refs/heads/main')
  self.assertEqual(role['bound_claims']['environment'],'dev');self.assertEqual(role['bound_claims']['ref'],'refs/heads/main')
  self.assertEqual(role['token_policies'],['github-actions-playbooks-feature-seed-sit'])
  policy=(ROOT/'scripts/vault/policies/github-actions-playbooks-feature-seed-sit.hcl').read_text()
  self.assertEqual(policy.count('path '),1);self.assertIn('kv/data/CICD/dev/k3s-bootstrap',policy);self.assertNotIn('ghcr',policy)
if __name__=='__main__':unittest.main()
