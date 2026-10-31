#!/usr/bin/env python3
"""Contracts for the compact five-run Selfhost parent orchestrator."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os
import re
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
STAGES = ("resolve", "infra", "deploy", "migrate", "verify")
PARENT_JOBS = ("resolve", "infrastructure", "deploy", "migrate", "verify")
SCRIPT = ROOT / ".github/scripts/platform-ops/stage-dispatch.py"
SPEC = spec_from_file_location("stage_dispatch", SCRIPT)
stage_dispatch = module_from_spec(SPEC)
SPEC.loader.exec_module(stage_dispatch)


def load_workflow(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


class SelfhostStageDispatchContractTest(unittest.TestCase):
    def test_k3s_target_selection_requires_exactly_one_contained_manifest(self):
        spec = spec_from_file_location('k3s_target', ROOT / 'scripts/ci/select_k3s_manifest.py')
        selector = module_from_spec(spec)
        spec.loader.exec_module(selector)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cmdb.json').write_text('{"node": {"host_vars": {"deployment_mode": "kubernetes"}}}')
            (root / 'resource.yaml').write_text('hosts:\n- name: node\n  host_vars:\n    deployment_mode: kubernetes\n')
            (root / 'target.yaml').write_text('targets:\n- stages:\n    resources:\n      manifest: resource.yaml\n')
            self.assertEqual('resource.yaml', selector.select(root, 'target.yaml', root / 'cmdb.json', 'node'))
            with self.assertRaises(ValueError):
                selector.writer_role(root, 'resource.yaml', 'node')
            (root / 'resource.yaml').write_text('hosts:\n- name: node\n  host_vars:\n    deployment_mode: kubernetes\n    k3s_identity_vault_writer_role: scoped-writer\n')
            self.assertEqual('scoped-writer', selector.writer_role(root, 'resource.yaml', 'node'))
            with self.assertRaises(ValueError):
                selector.bootstrap_reader(root, 'resource.yaml', 'node')
            with (root / 'resource.yaml').open('a') as stream:
                stream.write('    k3s_platform_vault_bootstrap_reader_role: scoped-reader\n    k3s_platform_vault_ssh_key_path: kv/data/prod/platform/cluster/ssh\n    k3s_platform_vault_ssh_key_field: SSH_PRIVATE_KEY\n')
            self.assertEqual('scoped-reader', selector.bootstrap_reader(root, 'resource.yaml', 'node')['role'])
            (root / 'target.yaml').write_text('targets:\n- stages:\n    resources:\n      manifest: ../outside.yaml\n')
            with self.assertRaises(ValueError):
                selector.select(root, 'target.yaml', root / 'cmdb.json', 'node')

    def test_k3s_catalog_selects_exact_scope_and_refuses_ambiguity(self):
        spec = spec_from_file_location('k3s_catalog', ROOT / 'scripts/ci/select_k3s_manifest.py')
        selector = module_from_spec(spec)
        spec.loader.exec_module(selector)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cmdb.json').write_text('{"node":{"deployment_mode":"kubernetes"}}')
            (root / 'resource.yaml').write_text('hosts:\n- name: node\n  host_vars: {deployment_mode: kubernetes}\n')
            entry = {'environment': 'prod', 'provider': 'cloud', 'account': 'account', 'workspace': 'cluster', 'stages': {'resources': {'manifest': 'resource.yaml'}}}
            (root / 'target.yaml').write_text(yaml.safe_dump({'targets': [entry]}))
            (root / 'catalog.yaml').write_text(yaml.safe_dump({'kind': 'IaCTargetCatalog', 'target_manifests': ['target.yaml']}))
            self.assertEqual('resource.yaml', selector.select(root, 'catalog.yaml', root / 'cmdb.json', 'node', 'prod', 'cloud', 'account', 'cluster'))
            with self.assertRaises(ValueError):
                selector.select(root, 'catalog.yaml', root / 'cmdb.json', 'node', 'prod', 'cloud', 'wrong-account', 'cluster')
            (root / 'target.yaml').write_text(yaml.safe_dump({'targets': [entry, entry]}))
            with self.assertRaises(ValueError):
                selector.select(root, 'catalog.yaml', root / 'cmdb.json', 'node', 'prod', 'cloud', 'account', 'cluster')

    def test_k3s_owner_inputs_and_tls_ownership_are_wired(self):
        workflow = load_workflow(ROOT / '.github/workflows/selfhost-stage-deploy.yml')
        steps = workflow['jobs']['deploy_base']['steps']
        bootstrap = next(step for step in steps if step.get('name') == 'Bootstrap node according to CMDB role')
        writer = next(step for step in steps if step.get('name') == 'Obtain scoped Vault writer for Kubernetes identities')
        self.assertLess(steps.index(writer), steps.index(bootstrap))
        self.assertIn('K3S_IDENTITY_VAULT_TOKEN', writer['run'])
        self.assertIn('::add-mask::', writer['run'])
        for key in ('K3S_GITOPS_CHECKOUT', 'K3S_GITOPS_SHA', 'K3S_RESOURCE_MANIFEST', 'K3S_CMDB_SHA256', 'K3S_BOOTSTRAP_RECEIPT'):
            self.assertIn(key, bootstrap['env'])
        for name in ('Read domain TLS record through the authorized Vault session', 'Read the brand-domain certificate from its Vault KV path'):
            step = next(step for step in steps if step.get('name') == name)
            self.assertIn("steps.k3s_target.outputs.manifest == ''", step['if'])

    def test_native_web_saas_jobs_do_not_target_kubernetes_hosts(self):
        workflow = load_workflow(ROOT / '.github/workflows/selfhost-stage-deploy.yml')
        for job_name in ('capture_web_saas_baseline', 'deploy_web_saas', 'accept_web_saas_upgrade'):
            job = workflow['jobs'][job_name]
            self.assertIn('hosts_web_saas_native', job['if'])
            self.assertIn('hosts_web_saas_native', job['strategy']['matrix']['host'])
        infra = load_workflow(ROOT / '.github/workflows/selfhost-stage-infra.yml')
        select = next(t for t in infra['jobs']['provision']['steps'] if t.get('id') == 'bootstrap_selection')
        self.assertIn('deployment_mode', select['run'])
        self.assertIn('hosts_kubernetes', select['run'])
        vault = next(t for t in infra['jobs']['provision']['steps'] if t.get('name') == 'Authenticate Vault for the existing application credential preparation')
        self.assertIn('steps.bootstrap_selection.outputs.hosts_kubernetes', vault['if'])
        self.assertIn('steps.bootstrap_selection.outputs.hosts_web_saas_native', vault['if'])

    def test_infra_evidence_is_carried_into_deploy_context(self):
        infra = load_workflow(ROOT / '.github/workflows/selfhost-stage-infra.yml')
        deploy = load_workflow(ROOT / '.github/workflows/selfhost-stage-deploy.yml')
        source = infra['jobs']['provision']
        digest = next(step for step in source['steps'] if step.get('id') == 'cmdb_digest')
        upload = next(step for step in source['steps'] if step.get('name') == 'Upload CMDB artifact')
        self.assertLess(source['steps'].index(digest), source['steps'].index(upload))
        self.assertIn('sha256sum', digest['run'])
        self.assertIn('cmdb-artifact/cmdb.json', digest['env']['CMDB_PATH'])
        for field in ('target_manifest', 'gitops_sha', 'cmdb_sha256'):
            self.assertIn(field, source['outputs'])
            self.assertIn(field, deploy['jobs']['provision']['outputs'])
            self.assertIn('outputs.' + field, deploy['jobs']['provision']['outputs'][field])
    def test_parent_graph_has_five_dispatch_and_wait_jobs(self):
        parent = load_workflow(ROOT / ".github/workflows/selfhost-orchestrator.yml")
        jobs = parent["jobs"]
        self.assertEqual(list(jobs), list(PARENT_JOBS))
        self.assertFalse(any(job.startswith('v6-') for job in jobs))
        self.assertNotIn("id-token", parent["permissions"])
        request_step = next(step for step in jobs["resolve"]["steps"] if step.get("id") == "request")
        self.assertEqual(
            request_step["env"]["REQUEST_INPUTS_JSON"],
            "${{ toJSON(inputs || github.event.inputs || fromJSON('{}')) }}",
        )
        for stage, job_id in zip(STAGES, PARENT_JOBS, strict=True):
            job = jobs[job_id]
            self.assertEqual(job["runs-on"], "ubuntu-latest", stage)
            self.assertNotIn("uses", job, stage)
            dispatch = next(step for step in job["steps"] if step.get("id") == "dispatch")
            self.assertIn("stage-dispatch.py", dispatch["run"], stage)
        self.assertEqual(jobs["infrastructure"]["needs"], "resolve")
        self.assertEqual(jobs["deploy"]["needs"], ["resolve", "infrastructure"])
        self.assertEqual(jobs["migrate"]["needs"], ["resolve", "infrastructure", "deploy"])
        self.assertEqual(jobs["verify"]["needs"], ["resolve", "infrastructure", "deploy", "migrate"])
        self.assertIn("operation != 'plan'", jobs["migrate"]["if"])
        self.assertIn("dns_mode == 'none'", jobs["migrate"]["if"])
        self.assertIn("skip_stripe_catalog == true", jobs["migrate"]["if"])
        self.assertIn("needs.resolve.result == 'success'", jobs["verify"]["if"])
        self.assertIn("needs.infrastructure.result == 'success'", jobs["verify"]["if"])
        self.assertIn("needs.deploy.result == 'success'", jobs["verify"]["if"])
        self.assertIn("needs.migrate.result == 'skipped'", jobs["verify"]["if"])
        verify_stage = load_workflow(ROOT / ".github/workflows/selfhost-stage-verify.yml")
        verify_inputs = verify_stage["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(verify_inputs["migration_context"]["required"], "false")
        self.assertEqual(verify_inputs["migration_run_id"]["required"], "false")

    def test_verify_allows_missing_migration_only_for_non_migrating_requests(self):
        common = {"migration_context": "", "migration_run_id": ""}
        self.assertTrue(stage_dispatch.migration_stage_may_be_skipped({"operation": "plan"}))
        self.assertTrue(stage_dispatch.migration_stage_may_be_skipped({
            "operation": "deploy", "dns_mode": "none", "skip_stripe_catalog": True,
        }))
        self.assertFalse(stage_dispatch.migration_stage_may_be_skipped({
            "operation": "deploy", "dns_mode": "none", "skip_stripe_catalog": False,
        }))
        self.assertFalse(stage_dispatch.migration_stage_may_be_skipped({
            "operation": "deploy+migrate", "dns_mode": "none", "skip_stripe_catalog": True,
        }))
        verify_prior = stage_dispatch.verification_prior_stages(
            "verify", {"operation": "deploy", "dns_mode": "none", "skip_stripe_catalog": True}, common,
        )
        self.assertEqual([stage for stage, _, _ in verify_prior], ["infra", "deploy"])
        with self.assertRaises(SystemExit):
            stage_dispatch.verification_prior_stages(
                "verify",
                {"operation": "plan"},
                {"migration_context": "{}", "migration_run_id": "123"},
            )

    def test_dispatched_stage_requires_parent_and_uploads_context(self):
        for stage in STAGES:
            workflow_path = ROOT / f".github/workflows/selfhost-stage-{stage}.yml"
            workflow = load_workflow(workflow_path)
            dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
            self.assertLessEqual(len(dispatch_inputs), 10, stage)
            input_refs = set(re.findall(r"\binputs\.([A-Za-z_][A-Za-z0-9_-]*)", workflow_path.read_text(encoding="utf-8")))
            self.assertLessEqual(input_refs, set(dispatch_inputs), (stage, sorted(input_refs - set(dispatch_inputs))))
            for field in ("payload_json", "parent_run_id", "parent_run_attempt", "correlation_id"):
                self.assertEqual(dispatch_inputs[field]["required"], "true", (stage, field))
            self.assertIn("parent-gate", workflow["jobs"])
            gate = workflow["jobs"]["parent-gate"]
            self.assertIn("verify-parent", gate["steps"][-1]["run"])

            def depends_on_gate(job_id, seen=None):
                seen = set() if seen is None else seen
                if job_id == "parent-gate":
                    return True
                if job_id in seen:
                    return False
                seen.add(job_id)
                needs = workflow["jobs"][job_id].get("needs", [])
                needs = [needs] if isinstance(needs, str) else needs
                return any(depends_on_gate(dependency, seen) for dependency in needs)

            for job_id in workflow["jobs"]:
                self.assertTrue(depends_on_gate(job_id), (stage, job_id))
            if stage != "verify":
                output = workflow["jobs"]["stage-output"]
                artifact = next(step for step in output["steps"] if step.get("uses") == "actions/upload-artifact@v7")
                self.assertEqual(artifact["with"]["name"], f"selfhost-stage-context-{stage}")

    def test_cross_run_context_artifacts_are_bound_to_exact_runs(self):
        infra = (ROOT / ".github/workflows/selfhost-stage-infra.yml").read_text(encoding="utf-8")
        self.assertIn("iac-existing-host-${{ inputs.resolve_run_id }}-${{ inputs.resolve_run_attempt }}", infra)
        for stage in ("deploy", "migrate", "verify"):
            workflow = load_workflow(ROOT / f".github/workflows/selfhost-stage-{stage}.yml")
            downloads = [
                step for job in workflow["jobs"].values()
                for step in job.get("steps", [])
                if step.get("uses", "").startswith("actions/download-artifact@")
                and step.get("with", {}).get("name") == "platform-ops-toolkit-cmdb"
            ]
            for download in downloads:
                self.assertEqual(download["with"]["run-id"], "${{ inputs.infra_run_id }}")
                self.assertEqual(download["with"]["repository"], "${{ github.repository }}")

    def test_child_run_lookup_requires_exact_correlation_name(self):
        original = stage_dispatch.gh
        try:
            stage_dispatch.gh = lambda *_args, **_kwargs: {
                "workflow_runs": [
                    {"id": 1, "display_title": "Selfhost Stage resolve-123-1"},
                    {"id": 2, "display_title": "Selfhost Stage resolve-123-10"},
                ]
            }
            selected = stage_dispatch.find_child("org/repo", "child.yml", "2026-01-01T00:00:00Z", "resolve-123-1")
            self.assertEqual(selected["id"], 1)
        finally:
            stage_dispatch.gh = original

    def test_parent_run_identifiers_are_numeric_before_api_lookup(self):
        self.assertEqual(stage_dispatch.require_positive_decimal("12345", "Parent run ID"), "12345")
        for value in ("0", "-1", "12/../../secrets", "１２３"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                stage_dispatch.require_positive_decimal(value, "Parent run ID")

    def test_terminal_verify_stage_uses_run_conclusion_without_context_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output"
            summary = Path(directory) / "step-summary"
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
            }), patch("subprocess.run", side_effect=AssertionError("verify must not download a context artifact")):
                stage_dispatch.download_context(
                    "org/repo",
                    {"id": 123, "run_attempt": 2, "html_url": "https://example.invalid/run/123"},
                    "verify",
                )
            self.assertIn("run_id=123", output.read_text(encoding="utf-8"))
            self.assertIn("run_attempt=2", output.read_text(encoding="utf-8"))
            self.assertIn("open child run", summary.read_text(encoding="utf-8"))

    def test_stage_context_fields_are_valid_context_inputs(self):
        source = SCRIPT.read_text(encoding="utf-8")
        match = re.search(r"if key not in \{([^}]+)\}:", source)
        self.assertIsNotNone(match)
        allowed = {token.strip().strip("'\"") for token in match.group(1).split(",") if token.strip()}
        declared = set().union(*stage_dispatch.STAGE_CONTEXT_FIELDS.values())
        self.assertTrue(declared.issubset(allowed), f"Missing allowed fields: {declared - allowed}")


if __name__ == "__main__":
    unittest.main()

