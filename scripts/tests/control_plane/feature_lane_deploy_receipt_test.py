#!/usr/bin/env python3
import importlib.util
import hashlib
import json
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
        self.candidate = {'feature_id':'sit-test-1483','feature_tag':'smoke-sit-test-1483','chart_digest':'sha256:'+'d'*64,'data_baseline_sha256':'d'*64,'gitops': {'repository': 'ai-workspace-infra/gitops', 'sha': 'b'*40}}
        inputs = {'schema': 'sit-data-input/v1'}
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.candidate['data_baseline_sha256'] = digest
        self.gate = Mock()
        self.gate.sha.side_effect = lambda x, length=40: isinstance(x, str) and len(x) == length and all(c in '0123456789abcdef' for c in x)
        self.gate.identity.return_value = 'c'*64
        components={name:{} for name in ('caddy','postgresql','console','accounts','billing','content')}
        knowledge={'repository':'ai-workspace-services/knowledge','sha':'e'*40}
        projection={'tagged_lane':{'feature_id':'sit-test-1483','feature_tag':'smoke-sit-test-1483','candidate_sha256':'c'*64},'chart_digest':self.candidate['chart_digest'],'knowledge':knowledge,'components':components}
        self.gate.gate.return_value = {'status': 'VERIFIED_GATE', 'dispatch_authorized': False, 'execution': 'NOT_RUN', 'candidate_sha256': 'c'*64, 'verified_projection': projection,'verified_runtime_components':components,'verified_chart_digest':self.candidate['chart_digest'],'verified_website_content':knowledge,'verified_data_baseline':{'sha256':digest, 'inputs':inputs}}

    def test_receipt_revalidates_in_same_run_without_deploy(self):
        receipt = module.build_receipt(self.candidate, {}, self.env, self.gate)
        self.assertEqual(receipt['source']['run_id'], '123')
        self.assertEqual(receipt['candidate_head'], 'b'*40)
        self.assertEqual(receipt['data_baseline_inputs'], {'schema': 'sit-data-input/v1'})
        self.gate.gate.assert_called_once_with(self.candidate, stage='sit', policy_commit='a'*40, evidence_selectors={})

    def test_context_and_fingerprint_mismatch_rejected(self):
        for key, value in [('GITHUB_REF', 'refs/tags/feature'), ('GITHUB_RUN_ATTEMPT', '0'), ('GITHUB_WORKFLOW_REF', 'other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.build_receipt(self.candidate, {}, dict(self.env, **{key: value}), self.gate)
        self.gate.gate.return_value['verified_projection']['tagged_lane']['candidate_sha256'] = 'd'*64
        with self.assertRaises(ValueError):
            module.build_receipt(self.candidate, {}, self.env, self.gate)

    def test_data_baseline_mismatch_is_rejected(self):
        self.gate.gate.return_value['verified_data_baseline']['sha256'] = 'e'*64
        with self.assertRaises(ValueError):
            module.build_receipt(self.candidate, {}, self.env, self.gate)

    def test_changed_baseline_input_is_rejected(self):
        self.gate.gate.return_value['verified_data_baseline']['inputs']['schema'] = 'changed'
        with self.assertRaises(ValueError):
            module.build_receipt(self.candidate, {}, self.env, self.gate)

    def test_incomplete_or_inconsistent_projection_rejected(self):
        self.gate.gate.return_value['verified_projection']['components'].pop('billing')
        with self.assertRaises(ValueError):
            module.build_receipt(self.candidate, {}, self.env, self.gate)


if __name__ == '__main__':
    unittest.main()
