"""Falsify the five-stage parent, evidence handoffs and failure reporting."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
WF = ROOT / '.github/workflows'
SCRIPT = ROOT / '.github/actions/serverless-stage-result/result.py'
spec = importlib.util.spec_from_file_location('serverless_result', SCRIPT)
result = importlib.util.module_from_spec(spec)
spec.loader.exec_module(result)


def workflow(name):
    return yaml.safe_load((WF / name).read_text())


def success(stage):
    return {name: {'result': 'success', 'outputs': {}} for name in result.STAGES[stage]}


class ServerlessStages(unittest.TestCase):
    def test_exact_five_stage_parent_and_same_run_local_calls(self):
        parent = workflow('serverless-orchestrator.yml')
        jobs = parent['jobs']
        self.assertEqual(list(jobs), ['resolve', 'infrastructure', 'deploy', 'migrate', 'verify'])
        for index, (name, job) in enumerate(jobs.items(), 1):
            self.assertTrue(job['name'].startswith(f'[{index}/5]'))
            stage = 'infra' if name == 'infrastructure' else name
            self.assertEqual(job['uses'], f'./.github/workflows/serverless-stage-{stage}.yml')
            if index > 1:
                self.assertEqual(job['needs'], list(jobs)[:index-1])
            self.assertNotIn('secrets', job)
        self.assertIn('always()', jobs['verify']['if'])
        self.assertEqual(jobs['verify']['with']['stage_results'], '${{ toJSON(needs) }}')
        self.assertFalse(parent['concurrency']['cancel-in-progress'])
        self.assertEqual(parent['concurrency']['group'], "serverless-${{ inputs.vault_env_path || 'uat' }}")

    def test_all_consumed_inputs_are_declared_and_passed_with_native_types(self):
        import re
        parent = workflow('serverless-orchestrator.yml')
        trigger = parent.get('on', parent.get(True))['workflow_dispatch']['inputs']
        for job in parent['jobs'].values():
            child = workflow(job['uses'].rsplit('/', 1)[1])
            declared = child.get('on', child.get(True))['workflow_call']['inputs']
            referenced = set(re.findall(r'\binputs\.([a-z_][a-z_0-9]*)', json.dumps(child['jobs'])))
            self.assertLessEqual(referenced, declared.keys())
            self.assertEqual(set(job['with']), set(declared))
            for key in trigger.keys() & declared.keys():
                expected = trigger[key]['type']
                self.assertEqual(declared[key]['type'], 'string' if expected == 'choice' else expected)
                self.assertEqual(job['with'][key], '${{ inputs.' + key + ' }}')
        for name in ('resolve', 'deploy'):
            self.assertIn('accounts_schema_sha256', parent['jobs'][name]['with'])

    def test_no_dangling_needs_and_collectors_include_every_job(self):
        for stage, expected in result.STAGES.items():
            child = workflow(f'serverless-stage-{stage}.yml')
            jobs = child['jobs']
            self.assertEqual(set(jobs), set(expected) | {'stage_result'})
            self.assertEqual(set(jobs['stage_result']['needs']), set(expected))
            for job in jobs.values():
                needs = job.get('needs', [])
                needs = [needs] if isinstance(needs, str) else needs
                self.assertLessEqual(set(needs), set(jobs))
            self.assertIn('always()', jobs['stage_result']['if'])
            action = jobs['stage_result']['steps'][1]
            self.assertEqual(action['uses'], './.github/actions/serverless-stage-result')
            self.assertEqual(action['with']['results'], '${{ toJSON(needs) }}')

    def test_schema_and_backend_frontend_order_remains_strict(self):
        jobs = workflow('serverless-stage-deploy.yml')['jobs']
        for schema in ('uat_accounts_baseline', 'uat_accounts_schema_migration'):
            self.assertIn(schema, jobs['cloud_run']['needs'])
            self.assertIn(f'needs.{schema}.result == \'success\'', jobs['cloud_run']['if'])
        self.assertIn('cloud_run', jobs['backend_gate']['needs'])
        for frontend in ('cloudflare_ssr', 'edge_gateway', 'frontend_router'):
            self.assertIn('backend_gate', jobs[frontend]['needs'])
            self.assertIn("needs.backend_gate.result == 'success'", jobs[frontend]['if'])
        self.assertIn('cloudflare_ssr', jobs['static_pages']['needs'])
        self.assertIn("needs.cloudflare_ssr.result == 'success'", jobs['static_pages']['if'])
        self.assertIn('static_pages', jobs['frontend_router']['needs'])
        self.assertEqual(jobs['cloud_run']['strategy']['max-parallel'], 1)
        self.assertFalse(jobs['cloud_run']['strategy']['fail-fast'])
        self.assertTrue(workflow('serverless-stage-migrate.yml')['jobs']['stripe_catalog']['continue-on-error'])

    def test_exact_stage_claims_reuse_existing_environment_ref_allowlists(self):
        for environment in ('sit', 'uat', 'prod'):
            role = json.loads((ROOT / f'scripts/vault/roles/github-actions-platform-ops-toolkit-{environment}.json').read_text())
            claims = role['bound_claims']
            for stage in ('infra', 'deploy', 'migrate'):
                prefix = f'ai-workspace-infra/platform-ops-toolkit/.github/workflows/serverless-stage-{stage}.yml@'
                selected = [value.removeprefix(prefix) for value in claims['job_workflow_ref'] if value.startswith(prefix)]
                self.assertEqual(selected, claims['ref'])
                self.assertNotIn('*', selected)
            self.assertFalse(any('refs/heads/feature/' in value for value in claims['job_workflow_ref']))

    def run_stage(self, stage, jobs, prior=None):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            env = dict(os.environ, SERVERLESS_STAGE=stage, STAGE_JOBS=json.dumps(jobs),
                       STAGE_RESULTS=json.dumps(prior or {}), RUNNER_TEMP=directory,
                       GITHUB_RUN_ID='42', GITHUB_RUN_ATTEMPT='3', GITHUB_OUTPUT=str(output),
                       GITHUB_STEP_SUMMARY=str(Path(directory) / 'summary'))
            run = subprocess.run(['python3', str(SCRIPT)], env=env, capture_output=True, text=True)
            artifact = Path(directory) / f'serverless-stage-{stage}.json'
            return run, json.loads(artifact.read_text()) if artifact.exists() else None

    def test_failure_and_cancellation_fail_but_keep_exact_run_evidence(self):
        for status in ('failure', 'cancelled'):
            jobs = success('deploy')
            jobs['cloud_run']['result'] = status
            run, artifact = self.run_stage('deploy', jobs)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('cloud_run', run.stderr)
            self.assertEqual(artifact['run_id'], '42')
            self.assertEqual(artifact['run_attempt'], '3')
            self.assertEqual(artifact['context']['cloud_run']['result'], status)

    def test_intentionally_skipped_lanes_and_nonblocking_catalog_are_accepted(self):
        jobs = success('migrate')
        jobs['trigger_data_migration']['result'] = 'skipped'
        run, _ = self.run_stage('migrate', jobs)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_terminal_gate_rejects_skipped_failed_and_cancelled_parent_stages(self):
        for status in ('skipped', 'failure', 'cancelled'):
            prior = {name: {'result': 'success', 'outputs': {}} for name in result.PARENTS}
            prior['deploy']['result'] = status
            run, _ = self.run_stage('verify', success('verify'), prior)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('parent:deploy', run.stderr)

    def test_wrong_missing_unknown_and_non_string_results_are_rejected(self):
        fixtures = [{}, {'unexpected': {'result': 'success'}}, {'preflight': {'result': 'unknown'}},
                    {'preflight': {'result': 'success', 'outputs': {'gitops_ref': 42}}}]
        for jobs in fixtures:
            run, artifact = self.run_stage('resolve', jobs)
            self.assertNotEqual(run.returncode, 0)
            self.assertIsNone(artifact)

    def test_output_allowlist_drops_unexpected_values(self):
        jobs = success('resolve')
        jobs['preflight']['outputs'] = {'gitops_ref': 'a'*40, 'unexpected': 'must-not-be-retained'}
        run, artifact = self.run_stage('resolve', jobs)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(artifact['context']['preflight']['outputs'], {'gitops_ref': 'a'*40})

    def test_metadata_survives_missing_failed_child_outputs_and_strips_outputs(self):
        parents = {name: {'result': 'success', 'outputs': {'unexpected': 'must-not-be-retained'}} for name in result.PARENTS}
        parents['deploy']['result'] = 'failure'
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, STAGE_CONTEXTS='{}', STAGE_RESULTS=json.dumps(parents), VERIFY_RESULT='failure',
                       RELEASE_ENV='uat', RELEASE_TAG='daily-build-2026.10.24-r2', RELEASE_OPERATION='deploy', RELEASE_TARGET='web-saas')
            run = subprocess.run(['python3', str(SCRIPT), 'metadata'], env=env, cwd=directory, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            text = (Path(directory) / 'release-metadata.json').read_text()
            self.assertNotIn('must-not-be-retained', text)
            self.assertEqual(json.loads(text)['stages']['deploy']['result'], 'failure')


if __name__ == '__main__':
    unittest.main()
