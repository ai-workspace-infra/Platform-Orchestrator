import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / '.github/scripts/feature-lane/preflight.py'


class FeaturePreflightTest(unittest.TestCase):
    def test_missing_and_malformed_inputs_fail_without_leaking_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / 'candidate.json'
            selectors = Path(directory) / 'selectors.json'
            selectors.write_text('{}')
            env = dict(os.environ, FEATURE_CANDIDATE_FILE=str(candidate),
                       FEATURE_EVIDENCE_SELECTORS_FILE=str(selectors), FEATURE_STAGE='sit',
                       FEATURE_POLICY_COMMIT='not-a-valid-commit')
            for content in (None, '{"private-marker":'):
                if content is not None:
                    candidate.write_text(content)
                result = subprocess.run([sys.executable, str(ENTRY)], env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('private-marker', result.stderr + result.stdout)
                self.assertNotIn('VERIFIED_GATE', result.stdout)


if __name__ == '__main__':
    unittest.main()
