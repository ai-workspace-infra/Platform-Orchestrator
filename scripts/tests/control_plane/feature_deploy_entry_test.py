import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]

class FeatureDeployEntryTest(unittest.TestCase):
    def test_event_requires_authentication_before_scoped_candidate_receipt(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/feature-lane-deploy.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        self.assertEqual(triggers['workflow_run']['workflows'], ['Feature tag preflight'])
        jobs = workflow['jobs']
        self.assertIn('workflow_run', jobs['authenticate-event']['if'])
        self.assertEqual(jobs['verified-candidate']['needs'], 'authenticate-event')
        self.assertEqual(jobs['verified-candidate']['environment'], 'dev')
        steps = jobs['verified-candidate']['steps']
        run = next(step['run'] for step in steps if step.get('id') == 'receipt')
        self.assertIn('deploy-receipt.py', run)
        self.assertIn('sha256sum', run)
        self.assertTrue(any('upload-artifact@' in step.get('uses', '') for step in steps))
        self.assertNotIn('id-token', workflow['permissions'])
        for job in ('identity-allowed', 'identity-denied-environment'):
            self.assertIn('workflow_dispatch', jobs[job]['if'])

if __name__ == '__main__':
    unittest.main()
