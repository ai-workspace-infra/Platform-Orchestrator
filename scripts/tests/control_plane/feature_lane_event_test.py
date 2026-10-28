import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ENTRY = Path(__file__).resolve().parents[3] / '.github/scripts/feature-lane/event-preflight.py'


class FeatureEventTest(unittest.TestCase):
    def test_only_matching_main_candidate_reaches_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tag = 'smoke-sit-test-1483'
            candidate_dir = root / '.github/feature-candidates' / tag
            candidate_dir.mkdir(parents=True)
            script_dir = root / '.github/scripts/feature-lane'
            script_dir.mkdir(parents=True)
            (script_dir / 'preflight.py').write_text('import sys; sys.exit(42)')
            path = candidate_dir / 'candidate.json'
            env = dict(os.environ, GITHUB_WORKSPACE=str(root), FEATURE_EVENT_TAG=tag)
            path.write_text(json.dumps({'feature_tag': tag}))
            run = lambda: subprocess.run([sys.executable, str(ENTRY)], env=env, capture_output=True, text=True)
            self.assertEqual(run().returncode, 42)
            path.write_text(json.dumps({'feature_tag': 'other'}))
            self.assertEqual(run().returncode, 1)
            env['FEATURE_EVENT_TAG'] = '../invalid'
            self.assertEqual(run().returncode, 1)


if __name__ == '__main__':
    unittest.main()
