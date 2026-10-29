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
        self.assertIn('workflow_run', jobs['verified-candidate']['if'])
        self.assertEqual(jobs['verified-candidate']['environment'], 'dev')
        steps = jobs['verified-candidate']['steps']
        ids = [step.get('id') for step in steps]
        self.assertLess(ids.index('event'), ids.index('vault'))
        self.assertIn('main-event.py', steps[ids.index('event')]['run'])
        run = next(step['run'] for step in steps if step.get('id') == 'receipt')
        self.assertIn('deploy-receipt.py', run)
        self.assertIn('sha256sum', run)
        self.assertTrue(any('upload-artifact@' in step.get('uses', '') for step in steps))
        target = jobs['observe-target']
        self.assertEqual(target['needs'], 'verified-candidate')
        self.assertEqual(target['uses'], 'ai-workspace-infra/iac_modules/.github/workflows/feature-sit-target-observe.yml@61f79c73d1c415755989fa55c8a36a3b862b391d')
        self.assertEqual(target['with']['candidate_sha256'], '${{ needs.verified-candidate.outputs.sha256 }}')
        self.assertEqual(target['with']['cmdb_artifact'], '${{ needs.verified-candidate.outputs.cmdb_artifact }}')
        self.assertEqual(jobs['edge-preflight']['needs'], ['verified-candidate', 'observe-target'])
        dns = jobs['publish-dns']
        self.assertEqual(dns['needs'], ['verified-candidate', 'observe-target', 'edge-preflight'])
        self.assertEqual(dns['strategy']['matrix']['service'], ['console', 'accounts', 'billing'])
        self.assertIs(dns['strategy']['fail-fast'], False)
        self.assertEqual(dns['with']['hostname'], "${{ needs.verified-candidate.outputs[format('{0}_host', matrix.service)] }}")
        self.assertEqual(dns['with']['candidate_receipt_sha256'], '${{ needs.verified-candidate.outputs.sha256 }}')
        self.assertEqual(dns['uses'], 'ai-workspace-infra/iac_modules/.github/workflows/feature-sit-dns.yml@6cd679bd61abd8777669b6786a378ce014da3884')
        self.assertEqual(jobs['sit-prepare']['needs'], ['verified-candidate', 'publish-dns'])
        self.assertIn('acceptance not run', jobs['sit-prepare']['name'])
        self.assertEqual(jobs['sit-prepare']['with']['mode'], 'prepare')
        self.assertEqual(jobs['sit-prepare']['uses'], 'ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@92cfa9c3bde6b70ae4a70f435a3cee0d2b8e976e')
        self.assertNotIn('id-token', workflow['permissions'])
        for job in ('identity-allowed', 'identity-denied-environment'):
            self.assertIn('workflow_dispatch', jobs[job]['if'])

if __name__ == '__main__':
    unittest.main()
