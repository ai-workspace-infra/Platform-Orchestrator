import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('projection', ROOT / '.github/scripts/feature-lane/foundation-projection.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class Resolver:
    def foundation(self, reader, run, summary, bootstrap):
        assert (run, summary, bootstrap) == (1, 2, 3)
        raw = '{"dev-k3s-v5":{}}'
        return raw, {'cmdb_sha256': hashlib.sha256(raw.encode()).hexdigest()}

class FoundationProjectionTest(unittest.TestCase):
    def setUp(self):
        repo = 'ai-workspace-infra/Platform-Orchestrator'
        ref = repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
        self.env = {'GITHUB_REPOSITORY': repo, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_WORKFLOW_REF': ref,
                    'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '2'}
        self.receipt = {'schema_version': 'dev-feature-candidate/v2', 'result': 'verified', 'stage': 'sit',
                        'candidate_sha256': 'b'*64, 'source': {'repository': repo, 'workflow_ref': ref,
                        'workflow_sha': 'a'*40, 'run_id': '1', 'run_attempt': '2'}}
        self.policy = {'sit_foundation': {'run_id': 1, 'summary_artifact_id': 2, 'bootstrap_artifact_id': 3}}
    def test_valid_projection(self):
        raw, identity = p.project(self.policy, self.receipt, self.env, Resolver(), None)
        self.assertEqual(identity['cmdb_sha256'], hashlib.sha256(raw.encode()).hexdigest())
    def test_wrong_run_and_unreviewed_locator_fail(self):
        self.receipt['source']['run_id'] = '99'
        with self.assertRaises(ValueError): p.project(self.policy, self.receipt, self.env, Resolver(), None)
        self.receipt['source']['run_id'] = '1'
        self.policy['sit_foundation']['extra'] = 'unreviewed'
        with self.assertRaises(ValueError): p.project(self.policy, self.receipt, self.env, Resolver(), None)

if __name__ == '__main__': unittest.main()
