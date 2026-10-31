from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]


class FluxEventSummaryTest(unittest.TestCase):
    def test_dispatch_is_observation_only(self):
        path = ROOT / '.github/workflows/flux-event-summary.yml'
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertIn('repository_dispatch', workflow['on'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        jobs = workflow['jobs']
        self.assertEqual(list(jobs), ['summary'])
        job = jobs['summary']
        self.assertIn("'Kustomization/'", job['if'])
        self.assertIn("'HelmRelease/'", job['if'])
        self.assertNotIn('needs', job)
        step = job['steps'][0]
        self.assertIn('github.event.client_payload', step['env']['FLUX_EVENT'])
        self.assertIn('unverified', step['run'])
        self.assertNotIn('github.event.client_payload', step['run'])
        self.assertNotIn('kubectl', step['run'])


if __name__ == '__main__':
    unittest.main()
