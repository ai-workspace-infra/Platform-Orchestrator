#!/usr/bin/env python3
"""Exercise versioned production routing without dispatching or provisioning."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / ".github/scripts/platform-ops/provision/platform-ops_provision_route-ref-to-an-explicit-profile.sh"


class VersionedProdProfilesTest(unittest.TestCase):
    def test_akamai_generation_uses_declared_target_and_existing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / 'config').symlink_to(ROOT / 'config', target_is_directory=True)
            root = workspace / 'gitops'
            targets = root / 'iac/targets'
            targets.mkdir(parents=True)
            resource = root / 'resources/example/prod/akamai/web-saas-prod-v5.yaml'
            resource.parent.mkdir(parents=True)
            identity = dict(environment='prod', provider='akamai-cloud', account='fixture-account',
                            project='fixture-project', workspace='web-saas-prod-v5')
            state = 'terraform/prod/fixture-project/akamai-cloud/fixture-account/web-saas-prod-v5/terraform.tfstate'
            resource.write_text(yaml.safe_dump({'global': {**identity, 'region': 'fixture-region'},
                'hosts': [{'host_vars': {'target_generation': 'prod-v5'}}]}))
            target = {**identity, 'stages': {'resources': {'mode': 'terraform',
                'manifest': str(resource.relative_to(root)), 'requires_existing_state': True,
                'state': {'key': state}}}}
            manifest = targets / 'fixture.yaml'
            manifest.write_text(yaml.safe_dump({'targets': [target]}))
            result, values = self.route('prod-v5', GITHUB_WORKSPACE=str(workspace),
                INPUT_CLOUD_PROVIDER='akamai-cloud', INPUT_CLOUD_ACCOUNT='fixture-account')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(values['state_key'], state)
            self.assertEqual(values['terraform_namespace'], identity['workspace'])
            self.assertEqual(values['terraform_project'], identity['project'])
            self.assertEqual(Path(values['resource_files_full']).resolve(), resource.resolve())
            self.assertEqual(values['vault_env_path'], 'prod')
            target['stages']['resources']['state']['key'] = 'terraform/prod/wrong/terraform.tfstate'
            manifest.write_text(yaml.safe_dump({'targets': [target]}))
            refused, _ = self.route('prod-v5', GITHUB_WORKSPACE=str(workspace),
                INPUT_CLOUD_PROVIDER='akamai-cloud', INPUT_CLOUD_ACCOUNT='fixture-account')
            self.assertNotEqual(refused.returncode, 0)

    def test_akamai_generation_accepts_fresh_create_only_target(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / 'config').symlink_to(ROOT / 'config', target_is_directory=True)
            root = workspace / 'gitops'
            targets = root / 'iac/targets'
            targets.mkdir(parents=True)
            resource = root / 'resources/example/prod/akamai/prod-k3s-v6.yaml'
            resource.parent.mkdir(parents=True)
            identity = dict(environment='prod', provider='akamai-cloud', account='fixture-account',
                            project='fixture-project', workspace='prod-k3s-v6')
            state = 'terraform/prod/fixture-project/akamai-cloud/fixture-account/prod-k3s-v6/terraform.tfstate'
            resource.write_text(yaml.safe_dump({'global': {**identity, 'region': 'fixture-region'},
                'hosts': [{'host_vars': {'target_generation': 'prod-v6'}}]}))
            target = {**identity, 'stages': {'resources': {'mode': 'terraform',
                'manifest': str(resource.relative_to(root)), 'requires_existing_state': False,
                'create_only': True, 'state': {'key': state}}}}
            (targets / 'fixture.yaml').write_text(yaml.safe_dump({'targets': [target]}))
            result, values = self.route('prod-v6', GITHUB_WORKSPACE=str(workspace),
                INPUT_CLOUD_PROVIDER='akamai-cloud', INPUT_CLOUD_ACCOUNT='fixture-account')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(values['state_key'], state)
            self.assertEqual(values['terraform_namespace'], identity['workspace'])

    def route(self, profile="prod-v3", tag="", **overrides):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env = {
                **os.environ,
                "GITHUB_WORKSPACE": str(ROOT),
                "GITHUB_OUTPUT": str(output),
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/tags/v1.0.0",
                "GITHUB_REF_NAME": "v1.0.0",
                "INPUT_VAULT_ENV_PATH": profile,
                "INPUT_DEPLOY_TAG": tag,
                "INPUT_OPERATION": "plan",
                "INPUT_SOURCE_REF": "a" * 40,
                "INPUT_OFFLINE_MODE": "off",
                "INPUT_SOURCE_HOST": "install.svc.plus",
                "INPUT_SOURCE_DOMAIN_BASE": "svc.plus",
                "INPUT_TARGET_DOMAIN_BASE": "svc.plus",
                **overrides,
            }
            result = subprocess.run(["bash", str(ROUTE)], env=env, text=True, capture_output=True)
            values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
            return result, values

    def test_versions_share_prod_credentials_but_keep_state_isolated(self):
        for profile in ("prod-v2", "prod-v3", "prod-v12"):
            with self.subTest(profile=profile):
                result, values = self.route(profile, profile + "-2026.10.16-r1")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(values["deployment_env"], profile)
                self.assertEqual(values["vault_env_path"], "prod")
                self.assertEqual(values["state_key"], f"terraform/prod/{profile}.svc.plus/gcp-cloud/xworktech/web-saas-{profile}/terraform.tfstate")
                self.assertEqual(values["terraform_workspace"], f"{profile}-{profile}.svc.plus-gcp-cloud-xworktech-web-saas-{profile}")
                self.assertTrue(values["resource_files_full"].endswith(f"/resources/{profile}.svc.plus/prod/gcp/web-saas-{profile}.yaml"))
                self.assertEqual(values["agent_controller_url"], f"https://accounts-selfhost-{profile}.svc.plus")
                self.assertEqual(values["billing_service_base_url"], f"https://billing-selfhost-{profile}.svc.plus")
                for key in ("infra_ref", "playbooks_ref", "gitops_ref", "toolkit_ref", "console_ref"):
                    self.assertEqual(values[key], "a" * 40)

    def test_prod_tag_selects_same_profile_as_explicit_input(self):
        _, inferred = self.route("prod", "prod-v3-2026.10.16-r1")
        _, explicit = self.route("prod-v3", "prod-v3-2026.10.16-r1")
        self.assertEqual(inferred, explicit)

    def test_infra_plan_needs_no_application_tag(self):
        result, values = self.route()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values["deploy_tag"], "")

    def test_release_tags_remain_valid(self):
        result, _ = self.route(tag="v1.2.3")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reject_unsafe_or_mismatched_inputs(self):
        cases = [
            {"profile": "prod-v../3"},
            {"profile": "prod-vx"},
            {"tag": "prod-v3-"},
            {"tag": "prod-v3junk-release"},
            {"tag": "daily-build-2026.10.16"},
            {"tag": "main"},
            {"tag": "prod-v2-2026.10.16-r1"},
            {"profile": "uat", "tag": "prod-v3-2026.10.16-r1"},
            {"INPUT_STATE_PROJECT": "prod-v2.svc.plus"},
            {"INPUT_CLOUD_PROVIDER": "aws-cloud"},
            {"INPUT_OPERATION": "destroy"},
            {"GITHUB_REF": "refs/heads/codex/untrusted"},
        ]
        for inputs in cases:
            with self.subTest(inputs=inputs):
                result, _ = self.route(**inputs)
                self.assertNotEqual(result.returncode, 0)

    def test_existing_prod_and_uat_routes(self):
        for profile, zone in (("prod", "svc.plus"), ("uat", "onwalk.net")):
            result, values = self.route(profile, INPUT_TARGET_DOMAIN_BASE=zone)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(values["vault_env_path"], profile)
            self.assertTrue(values["resource_files_full"].endswith(f"/resources/{zone}/{profile}/gcp/web-saas.yaml"))

    def test_iac_dispatch_normalizes_profiles_to_production(self):
        spec = importlib.util.spec_from_file_location(
            "iac_dispatch", ROOT / ".github/scripts/platform-ops/provision/dispatch-iac-pipeline.py"
        )
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        class DispatchCaptured(Exception):
            pass
        for profile in ("prod-v2", "prod-v3", "prod-v12"):
            captured = []
            def capture(*args, **kwargs):
                captured.append(kwargs["payload"])
                raise DispatchCaptured()
            env = {
                "GITHUB_REPOSITORY": "example/toolkit", "IAC_ACTION": "plan",
                "IAC_ENVIRONMENT": profile, "IAC_TARGET_MANIFEST": "manifest.json",
                "IAC_GITOPS_REF": "a" * 40, "IAC_REF": "b" * 40,
                "IAC_STAGE_SCOPE": "resources", "IAC_BOOTSTRAP_MODE": "verify",
                "IAC_DISPATCH_REF": "v1.2.3", "IAC_CORRELATION_ID": "test",
                "IAC_SELECTORS": json.dumps({"environment": profile}),
            }
            with self.subTest(profile=profile), patch.dict(os.environ, env), patch.object(dispatcher, "gh", capture):
                with self.assertRaises(DispatchCaptured):
                    dispatcher.main()
                self.assertEqual(captured[0]["inputs"]["environment"], "prod")
                self.assertEqual(json.loads(captured[0]["inputs"]["selectors"])["environment"], "prod")

    def test_versioned_workflow_input_is_open_and_vault_refs_are_release_only(self):
        import yaml
        parent = yaml.load((ROOT / ".github/workflows/selfhost-orchestrator.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(parent["on"]["workflow_dispatch"]["inputs"]["vault_env_path"]["type"], "string")
        for stage in ("resolve", "infra", "deploy", "migrate", "verify"):
            workflow = yaml.load((ROOT / f".github/workflows/selfhost-stage-{stage}.yml").read_text(), Loader=yaml.BaseLoader)
            for key, value in workflow["env"].items():
                if key in {"VAULT_ENV_PATH", "VAULT_ROLE", "VAULT_KV_BASE", "VAULT_KV_BILLING", "VAULT_KV_DATABASES", "VAULT_KV_SMTP", "VAULT_KV_AGENT_PROXY", "VAULT_KV_IAC_STATE"}:
                    self.assertIn("startsWith(", value, (stage, key))
                    self.assertIn("'prod-v'", value, (stage, key))
        role = json.loads((ROOT / "scripts/vault/roles/github-actions-platform-ops-toolkit-prod-gcp-oidc-xworktech.json").read_text())
        self.assertEqual(set(role["bound_claims"]["ref"]), {"refs/tags/v*", "refs/heads/release/v*", "refs/tags/prod-v*", "refs/heads/release/prod-v*"})


if __name__ == "__main__":
    unittest.main()
