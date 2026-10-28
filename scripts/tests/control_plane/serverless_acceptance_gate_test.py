"""Negative admission and false-green regression tests; no live credentials."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / '.github/scripts/serverless/acceptance_gate.py'
spec = importlib.util.spec_from_file_location('gate', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class AcceptanceTests(unittest.TestCase):
    def stages(self, result='skipped'):
        return {name: {'result': 'success' if name == 'prepare' else result}
                for name in gate.STAGES}

    def receipt(self, stages, op='plan'):
        return gate.receipt(stages, 'uat', op, 'daily-build-2026.10.28-r1', '12', '2', 'a' * 40)

    def test_plan_only_and_dns_mutation_denied(self):
        for env in ('uat', 'prod'):
            gate.admit(env, 'plan', 'none')
            with self.assertRaises(ValueError):
                gate.admit(env, 'plan', 'uat-records')
        doc = self.receipt(self.stages())
        self.assertEqual('PLAN_ONLY', doc['overall_status'])
        self.assertFalse(doc['release_accepted'])
        self.assertEqual('2', doc['run_attempt'])

    def test_all_mutations_blocked_in_both_environments(self):
        for env in ('uat', 'prod'):
            for op in gate.OPERATIONS[1:]:
                with self.subTest(env=env, op=op), self.assertRaisesRegex(ValueError, 'owner execution'):
                    gate.admit(env, op, 'none')

    def test_successful_placeholders_never_accept_release(self):
        for op in gate.OPERATIONS[1:]:
            doc = self.receipt(self.stages('success'), op)
            self.assertEqual('BLOCKED', doc['overall_status'])
            self.assertFalse(doc['release_accepted'])

    def test_failed_cancelled_and_unexpected_plan_execution_blocked(self):
        for name in gate.STAGES:
            for result in ('failure', 'cancelled', 'success' if name != 'prepare' else 'skipped'):
                stages = self.stages()
                stages[name]['result'] = result
                self.assertEqual('BLOCKED', self.receipt(stages)['overall_status'])

    def test_missing_unknown_stage_and_bad_identity_rejected(self):
        for stages in ({}, {**self.stages(), 'other': {'result': 'success'}},
                       {**self.stages(), 'prepare': {'result': 'unknown'}}):
            with self.assertRaises(ValueError):
                self.receipt(stages)
        with self.assertRaises(ValueError):
            gate.receipt(self.stages(), 'uat', 'plan', '', '0', '1', 'a'*40)

    def test_blocked_summary_writes_negative_receipt_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'ENV_TARGET': 'uat', 'OP_TARGET': 'init',
                   'STAGE_RESULTS': json.dumps(self.stages('success')), 'GITHUB_RUN_ID': '12',
                   'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SHA': 'a'*40,
                   'GITHUB_OUTPUT': tmp+'/output', 'GITHUB_STEP_SUMMARY': tmp+'/summary'}
            run = subprocess.run(['python3', str(SCRIPT), 'summary'], cwd=tmp, env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(0, run.returncode)
            doc = json.loads(Path(tmp, 'serverless-delivery-receipt.json').read_text())
            self.assertEqual('BLOCKED', doc['overall_status'])

    def test_admission_precedes_resolve_and_vault(self):
        workflow = (ROOT / '.github/workflows/serverless-orchestrator.yml').read_text()
        self.assertLess(workflow.index('acceptance_gate.py admit'), workflow.index('id: resolve'))
        self.assertLess(workflow.index('acceptance_gate.py admit'), workflow.index('hashicorp/vault-action'))
        self.assertNotIn('receipt["overall_status"] = "FAILED" if failed_stages else "PASSED"', workflow)

    def test_dispatch_uses_current_inputs_and_rejects_sit(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock = Path(tmp, 'gh')
            mock.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                            'if sys.argv[1] == "workflow":\n'
                            ' open(os.environ["CALLS"],"w").write(json.dumps(sys.argv[1:]))\n'
                            ' print("https://github.com/ai-workspace-infra/Platform-Orchestrator/actions/runs/12")\n'
                            'else: print("completed\\tsuccess")\n')
            mock.chmod(0o755)
            env = {**os.environ, 'PATH': tmp+os.pathsep+os.environ['PATH'], 'GH_TOKEN': 'offline',
                   'SNAPSHOT_TAG': 'daily-build-2026.10.28-r1', 'DEPLOY_ENV': 'uat',
                   'DISPATCH_WORKFLOW': 'serverless-orchestrator.yml', 'TARGET_DOMAIN_BASE': 'example.test',
                   'GITHUB_OUTPUT': tmp+'/output', 'CALLS': tmp+'/calls'}
            script = ROOT / '.github/scripts/snapshots/dispatch-environment-combined.sh'
            run = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stderr)
            args = json.loads(Path(tmp, 'calls').read_text())
            self.assertIn('environment=uat', args)
            self.assertIn('release_tag=daily-build-2026.10.28-r1', args)
            self.assertNotIn('vault_env_path=uat', args)
            self.assertNotIn('deploy_cloud_run=true', args)
            Path(tmp, 'calls').unlink()
            for target, tag in (('sit', env['SNAPSHOT_TAG']), ('prod', 'v1.0.0')):
                run = subprocess.run(['bash', str(script)], env={**env, 'DEPLOY_ENV': target, 'SNAPSHOT_TAG': tag},
                                     capture_output=True, text=True)
                self.assertNotEqual(0, run.returncode)
                self.assertFalse(Path(tmp, 'calls').exists())


if __name__ == '__main__':
    unittest.main()
