#!/usr/bin/env python3
"""Offline contracts for the delivery DAG and caller handoff (no cloud calls)."""
import ast
import copy
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
import yaml
import workflow_gating_verify as gates

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / '.github/workflows'
def load(name):
    return yaml.safe_load((WF / name).read_text())


def triggers(workflow):
    # PyYAML 1.1 may parse the unquoted key `on` as boolean True.
    return workflow.get('on', workflow.get(True))

class UnifiedWorkflowContract(unittest.TestCase):
    def test_independent_forward_reverse_dags_and_exact_terminal_gate(self):
        jobs = load('iac-orchestrator.yml')['jobs']
        self.assertEqual(set(jobs), {'prepare','bootstrap','account','resources','destroy-resources','destroy-account','destroy-bootstrap','summary'})
        self.assertIn('bootstrap', jobs['account']['needs'])
        self.assertIn('account', jobs['resources']['needs'])
        self.assertIn('destroy-resources', jobs['destroy-account']['needs'])
        self.assertIn('destroy-account', jobs['destroy-bootstrap']['needs'])
        self.assertTrue(gates.terminal_iac_evidence_gate(jobs['summary'],jobs['summary']['needs']))
        broken = copy.deepcopy(jobs['summary'])
        next(s for s in broken['steps'] if s.get('uses','').endswith('/iac-summary'))['continue-on-error'] = True
        self.assertFalse(gates.terminal_iac_evidence_gate(broken,broken['needs']))
        self.assertFalse(gates.terminal_iac_evidence_gate(jobs['summary'],['prepare']))
        self.assertFalse(gates.terminal_iac_evidence_gate({'steps':[{'run':'echo success'}]},jobs['summary']['needs']))

    def test_three_stage_module_and_static_matrix_have_one_execution_owner(self):
        stages = load('iac-pipeline-multi-cloud-stages.yaml')['jobs']
        self.assertEqual(set(stages), {'bootstrap','account','resources'})
        for name, job in stages.items():
            self.assertNotIn('needs',job)
            self.assertEqual(job['concurrency']['group'],'iac-state-${{ inputs.lock_key }}')
            self.assertFalse(job['concurrency']['cancel-in-progress'])
            self.assertTrue(any(s.get('uses') == './iac_modules/.github/actions/iac-'+name for s in job['steps']))
        jobs = load('iac-self-check-matrix.yml')['jobs']
        self.assertEqual(set(jobs),{'prepare','self-check','execute-iac','summary'})
        self.assertNotIn('uses', jobs['execute-iac'])
        self.assertNotIn('id-token', load('iac-self-check-matrix.yml')['permissions'])
        self.assertFalse(any('hashicorp/vault-action' in str(job) for job in jobs.values()))
        self.assertFalse(any('iac-self-check-matrix' in j.get('uses','') for j in load('iac-orchestrator.yml')['jobs'].values()))
        self.assertTrue(gates.terminal_iac_evidence_gate(jobs['summary'],jobs['summary']['needs']))

    def test_static_events_are_centralized_and_legacy_entries_are_retired(self):
        matrix_events = triggers(load('iac-self-check-matrix.yml'))
        self.assertEqual(set(matrix_events), {'workflow_dispatch','pull_request','push'})
        self.assertNotIn('action', matrix_events['workflow_dispatch']['inputs'])
        self.assertEqual(set(matrix_events['push']['branches']), {'main','release/**'})
        for event in ('push','pull_request'):
            paths = set(matrix_events[event]['paths'])
            self.assertIn('.github/workflows/iac-*', paths)
            self.assertIn('terraform-hcl-standard/**', paths)

        wrappers = (
            'iac-pipeline-multi-cloud-landingzone-baseline.yaml',
            'iac-pipeline-multi-cloud-account-matrix.yaml',
            'iac-pipeline-multi-cloud-resources-matrix.yaml',
            'gcp-iac-pipeline.yml', 'gcp-oidc-bootstrap.yml',
            'akamai-cloud-iac.yml', 'ucloud-iac.yml', 'gcp-uat-workload-sequence.yml',
            'iac-pipeline-multi-cloud-master.yaml',
        )
        for name in wrappers:
            self.assertFalse((WF / name).exists(), name)
        for path in WF.iterdir():
            workflow = load(path.name)
            for job in workflow.get('jobs', {}).values():
                for retired in wrappers:
                    self.assertNotEqual(job.get('uses'), './.github/workflows/' + retired, path.name)

    def test_shared_callers_resolve_resources_in_the_single_iac_entry(self):
        for name, jobs in {
            'vault-server.yml': ['gcp-shared'],
            'zitadel-server.yml': ['infrastructure'],
            'open-platform-orchestrator.yml': ['vault-iac', 'observability-iac', 'iam-iac'],
        }.items():
            for key in jobs:
                job = load(name)['jobs'][key]
                self.assertEqual(job['uses'], './.github/workflows/iac-orchestrator.yml')
                self.assertEqual(job['with']['cloud_provider'], 'gcp-cloud')
                self.assertEqual(job['with']['stage_scope'], 'resources')
                self.assertIn('resource_manifest', job['with'])
        prepare = load('iac-orchestrator.yml')['jobs']['prepare']['steps']
        normalize = next(step for step in prepare if step.get('id') == 'normalize')
        self.assertEqual(normalize['uses'], './iac_modules/.github/actions/iac-legacy-inputs')
        target = next(step for step in prepare if step.get('id') == 'targets')
        self.assertLess(prepare.index(normalize), prepare.index(target))
        self.assertEqual(target['with']['selectors'], '${{ inputs.selectors }}')

    def test_none_excludes_legacy_shared_hosts_from_ssh_bootstrap(self):
        workflow = load('selfhost-orchestrator.yml')
        choices = triggers(workflow)['workflow_dispatch']['inputs']['open_platform_service']
        self.assertEqual(choices['default'], 'none')
        infra = load('selfhost-stage-infra.yml')
        script = next(step['run'] for step in infra['jobs']['provision']['steps'] if step.get('id') == 'bootstrap_selection')
        fixture = {
            'shared': {'ip': '192.0.2.1', 'groups': ['infra_platform']},
            'vault': {'ip': '192.0.2.2', 'groups': ['open_platform']},
            'app': {'ip': '192.0.2.3', 'groups': ['web_saas']},
            'metadata': 'a platform fact, never an SSH target',
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cmdb.json').write_text(json.dumps(fixture))
            for selection, expected in [('none', ['app']), ('all', ['shared', 'vault', 'app'])]:
                output = root / (selection + '.output')
                environment = dict(os.environ, CMDB_FILE=str(root / 'cmdb.json'),
                                   OPEN_PLATFORM_SERVICE=selection, GITHUB_OUTPUT=str(output))
                result = subprocess.run(['bash', '-c', script], env=environment, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(output.read_text().strip().split('=', 1)[1]), expected)
        base = load('selfhost-stage-deploy.yml')['jobs']['deploy_base']
        self.assertIn('bootstrap_hosts', base['strategy']['matrix']['host'])

    def test_provider_choice_preserves_declarations_and_rejects_unknown_clouds(self):
        workflow = load('iac-orchestrator.yml')
        request = triggers(workflow)['workflow_dispatch']['inputs']
        registry = json.loads((ROOT / 'config/iac_provider_registry.json').read_text())
        expected = {name for name, spec in registry.items() if spec['provisioner'] == 'terraform'}
        self.assertEqual(set(request['cloud_provider']['options']), {'auto'} | expected)
        self.assertEqual(request['cloud_provider']['type'], 'choice')
        self.assertLess(list(request).index('cloud_provider'), list(request).index('target_manifest'))
        steps = workflow['jobs']['prepare']['steps']
        provider = next(step for step in steps if step.get('id') == 'provider')
        normalize = next(step for step in steps if step.get('id') == 'normalize')
        self.assertEqual(normalize['with']['inputs-json'], '${{ steps.provider.outputs.inputs_json }}')
        self.assertIn('steps.provider.outputs.cloud_provider', normalize['if'])
        with tempfile.TemporaryDirectory() as directory:
            for value in ['auto', '', *sorted(expected), 'ulighthost', 'unknown-cloud']:
                output = Path(directory) / (value or 'empty')
                original = {'cloud_provider': value, 'environment': 'uat',
                            'target_manifest': 'iac/targets/reviewed.yaml',
                            'selectors': '{"account":"reviewed"}'}
                env = dict(os.environ, REQUEST_INPUTS=json.dumps(original), GITHUB_OUTPUT=str(output))
                result = subprocess.run(['bash', '-c', provider['run']], env=env, capture_output=True, text=True, timeout=10)
                if value in {'ulighthost', 'unknown-cloud'}:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(output.exists())
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                values = dict(line.split('=', 1) for line in output.read_text().splitlines())
                normalized = json.loads(values['inputs_json'])
                expected_provider = '' if value == 'auto' else value
                self.assertEqual(values['cloud_provider'], expected_provider)
                self.assertEqual(normalized, dict(original, cloud_provider=expected_provider))

    def test_retired_toolkit_copies_are_absent_and_aws_recovery_waits_for_evidence(self):
        retired = (
            '.github/actions/terraform-command/action.yml',
            '.github/actions/setup-iac-env/action.yml',
            '.github/scripts/platform-ops/observe/platform-ops_iac-self-check.py',
            '.github/scripts/lib/cmdb-ssh-login.sh',
        )
        for relative in retired:
            self.assertFalse((ROOT / relative).exists(), relative)
        for relative in (
            'scripts/cloud/bootstrap/aws/reconcile_github_oidc_trust.sh',
            'scripts/cloud/bootstrap/aws/adopt_github_oidc_terraform_state.sh',
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_orchestrators_preserve_inputs_and_gate_exact_receipt(self):
        for name, gate in [('selfhost-orchestrator.yml','provision')]:
            workflow = load(name)
            trigger = workflow.get('on',workflow.get(True))
            self.assertLessEqual(len(trigger['workflow_dispatch']['inputs']),25)
            self.assertEqual(len(workflow['jobs']), 5)
            self.assertEqual([workflow['jobs'][job]['name'] for job in workflow['jobs']], [f'[{i}/5] {label}' for i,label in enumerate(('Resolve & Validate','IaC & Provision','Deploy','Migrate & Configure','Verify & Report'),1)])
            jobs = load('selfhost-stage-infra.yml')['jobs']
            self.assertIn('dispatch external pipeline', jobs['iac']['name'])
            self.assertEqual(jobs['iac']['steps'][-1]['run'], 'python3 .github/scripts/platform-ops/provision/dispatch-iac-pipeline.py')
            self.assertTrue(any(s.get('uses')=='./iac_modules/.github/actions/iac-receipt-verify' for s in jobs[gate]['steps']))

        serverless = load('serverless-orchestrator.yml')
        trigger = serverless.get('on', serverless.get(True))
        self.assertLessEqual(len(trigger['workflow_dispatch']['inputs']), 25)
        self.assertEqual(list(serverless['jobs']), ['prepare', 'database', 'backend', 'frontend', 'configure', 'summary'])
        options = trigger['workflow_dispatch']['inputs']['environment']['options']
        self.assertEqual(options, ['uat', 'prod'])

        steps = load('selfhost-stage-infra.yml')['jobs']['provision']['steps']
        vault = next(i for i,s in enumerate(steps) if s.get('uses')=='hashicorp/vault-action@v4')
        init = next(i for i,s in enumerate(steps) if s.get('name')=='Initialize Databases Credentials')
        self.assertLess(vault,init)

    def test_exact_artifact_id_download_uses_expected_flat_directory(self):
        # download-artifact ID mode creates a name subdirectory unless merging
        # is explicit, even for one ID. Consumers read report/summary at root.
        for name in ('iac-self-check-matrix.yml','selfhost-stage-resolve.yml','selfhost-stage-infra.yml','selfhost-stage-deploy.yml','selfhost-stage-migrate.yml','selfhost-stage-verify.yml','serverless-orchestrator.yml','serverless-stage-infra.yml','serverless-stage-deploy.yml','serverless-stage-verify.yml'):
            for job in load(name)['jobs'].values():
                for step in job.get('steps',[]):
                    if 'artifact-ids' in step.get('with',{}):
                        self.assertIs(step['with'].get('merge-multiple'),True,name)
                        self.assertNotIn(',',step['with']['artifact-ids'])

    def test_generated_shell_and_python_parse(self):
        names = ['iac-orchestrator.yml','iac-pipeline-multi-cloud-stages.yaml','iac-self-check-matrix.yml','aws-oidc-bootstrap.yml']
        for name in names:
            for job in load(name)['jobs'].values():
                for step in job.get('steps',[]):
                    if 'run' not in step:continue
                    source = re.sub(r'\$\{\{.*?\}\}', 'VALUE', step['run'],flags=re.S)
                    result = subprocess.run(['bash','-n'],input=source,text=True,capture_output=True)
                    self.assertEqual(result.returncode,0,name+': '+result.stderr)
                    for code in re.findall(r"python3 - <<'PYCODE'\n(.*?)\nPYCODE",source,re.S):
                        ast.parse(code,filename=name)

if __name__ == '__main__':unittest.main()
