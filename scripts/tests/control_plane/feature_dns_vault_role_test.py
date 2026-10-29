import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
class DnsRoleTest(unittest.TestCase):
 def test_exact_dns_owner_and_separate_policies(self):
  for name,policy in [('github-actions-feature-dns-write-sit','github-actions-feature-dns-write-sit'),('github-actions-feature-dns-target-read-sit','github-actions-feature-target-read-sit')]:
   role=json.loads((ROOT/'scripts/vault/roles'/f'{name}.json').read_text())
   self.assertEqual(role['token_policies'],[policy]);self.assertTrue(role['token_no_default_policy'])
   self.assertEqual(role['token_ttl'],'10m');self.assertEqual(role['token_max_ttl'],'10m')
   claims=role['bound_claims'];self.assertEqual(claims['environment'],'dev');self.assertEqual(claims['ref'],'refs/heads/main')
   self.assertEqual(claims['workflow_ref'],'ai-workspace-infra/Platform-Orchestrator/.github/workflows/feature-lane-deploy.yml@refs/heads/main')
   self.assertEqual(claims['job_workflow_ref'], ['ai-workspace-infra/iac_modules/.github/workflows/feature-sit-dns.yml@6cd679bd61abd8777669b6786a378ce014da3884', 'ai-workspace-infra/iac_modules/.github/workflows/feature-sit-dns.yml@3cfc12d95578885ecd267d7d09e049919ff10464'])
  self.assertEqual((ROOT/'scripts/vault/policies/github-actions-feature-dns-write-sit.hcl').read_text().count('path '),1)
if __name__=='__main__':unittest.main()
