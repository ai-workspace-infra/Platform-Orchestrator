import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('dns_inputs',ROOT/'.github/scripts/feature-lane/dns-inputs.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DnsInputTest(unittest.TestCase):
 def test_only_bound_candidate_projects_exact_hosts(self):
  repo='ai-workspace-infra/Platform-Orchestrator';ref=repo+'/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
  env={'GITHUB_REPOSITORY':repo,'GITHUB_REF':'refs/heads/main','GITHUB_WORKFLOW_REF':ref,'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'12','GITHUB_RUN_ATTEMPT':'1'}
  r={'schema_version':'dev-feature-candidate/v2','result':'verified','stage':'sit','repository':'ai-workspace-infra/gitops','candidate_head':'b'*40,'candidate_sha256':'c'*64,
     'source':{'repository':repo,'workflow_ref':ref,'workflow_sha':'a'*40,'run_id':'12','run_attempt':'1'},
     'projection':{'tagged_lane':{'feature_id':'sit-test-1483','feature_tag':'smoke-sit-test-1483','candidate_sha256':'c'*64}}}
  out=m.project(r,env);self.assertEqual(out['console_host'],'smoke-sit-test-1483-sit.onwalk.net');self.assertEqual(out['accounts_host'],'accounts-'+out['console_host'])
  for changed in ({'GITHUB_RUN_ID':'13'},{'GITHUB_REF':'refs/heads/not-main'}):
   with self.subTest(changed=changed),self.assertRaises(ValueError):m.project(r,{**env,**changed})
  r['projection']['tagged_lane']['feature_tag']='other-sit-test-9999'
  with self.assertRaises(ValueError):m.project(r,env)
if __name__=='__main__':unittest.main()
