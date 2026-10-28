#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('deploy_receipt', ROOT / '.github/scripts/feature-lane/deploy-receipt.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        repo = 'ai-workspace-infra/Platform-Orchestrator'
        self.env = {'GITHUB_REPOSITORY': repo, 'GITHUB_WORKFLOW_REF': repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main', 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}
        self.candidate = {'gitops': {'repository': 'ai-workspace-infra/gitops', 'sha': 'b'*40}}
        self.gate = Mock()
        self.gate.sha.side_effect = lambda x: isinstance(x, str) and len(x) == 40 and all(c in '0123456789abcdef' for c in x)
        self.gate.identity.return_value = 'c'*64
        self.gate.gate.return_value = {'status': 'VERIFIED_GATE', 'dispatch_authorized': False, 'execution': 'NOT_RUN', 'candidate_sha256': 'c'*64, 'verified_projection': {'tagged_lane': {'candidate_sha256': 'c'*64}}}

    def test_receipt_revalidates_in_same_run_without_deploy(self):
        receipt = module.build_receipt(self.candidate, {}, self.env, self.gate)
        self.assertEqual(receipt['source']['run_id'], '123')
        self.assertEqual(receipt['candidate_head'], 'b'*40)
        self.gate.gate.assert_called_once_with(self.candidate, stage='sit', policy_commit='a'*40, evidence_selectors={})

    def test_context_and_fingerprint_mismatch_rejected(self):
        for key, value in [('GITHUB_REF', 'refs/tags/feature'), ('GITHUB_RUN_ATTEMPT', '0'), ('GITHUB_WORKFLOW_REF', 'other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.build_receipt(self.candidate, {}, dict(self.env, **{key: value}), self.gate)
        self.gate.gate.return_value['verified_projection']['tagged_lane']['candidate_sha256'] = 'd'*64
        with self.assertRaises(ValueError):
            module.build_receipt(self.candidate, {}, self.env, self.gate)


if __name__ == '__main__':
    unittest.main()
