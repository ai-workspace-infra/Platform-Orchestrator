import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('gate', ROOT / '.github/scripts/feature-lane/gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class RehearsalCandidateTest(unittest.TestCase):
    def test_candidate_and_evidence_selectors_are_bound_to_policy(self):
        tag = 'smoke-sit-test-1483'
        directory = ROOT / '.github/feature-candidates' / tag
        candidate = json.loads((directory / 'candidate.json').read_text())
        selectors = json.loads((directory / 'evidence-selectors.json').read_text())
        policy = json.loads((ROOT / '.github/policies/feature-lane.json').read_text())
        digest = gate.validate_candidate(candidate, policy)
        binding = policy['feature_tags'][tag]
        self.assertEqual(binding['candidate_sha256'], digest)
        self.assertEqual(binding['task_url'], candidate['task_url'])
        self.assertTrue(gate.sha(binding['tag_object_sha']))
        self.assertTrue(gate.sha(binding['target_sha']))
        self.assertEqual(set(selectors), {'builds', 'chart', 'data_baseline'})
        self.assertEqual(set(selectors['builds']), {row['repository'] for row in candidate['sources']})
        for row in [*selectors['builds'].values(), selectors['chart'], selectors['data_baseline']]:
            self.assertEqual(set(row), {'run_id', 'attempt', 'artifact_id'})
            self.assertTrue(all(type(value) is int and value > 0 for value in row.values()))


if __name__ == '__main__':
    unittest.main()
