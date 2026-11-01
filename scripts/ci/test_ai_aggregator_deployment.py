"""Cover event selectors, resource templates and deployment preflight gates."""

import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from resolve_ai_aggregator_deployment import materialize, resolve


ROOT = Path(__file__).resolve().parents[2]


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = {
            "kind": "PersonalAIAggregator",
            "metadata": {"environment": "preview", "topology": "single-node"},
            "spec": {
                "enabled": False,
                "infrastructure": {
                    # Legacy selection fields must not override event inputs.
                    "provider": "aws", "lifecycle": "ephemeral",
                    "resource_contract": {"renderer": "terraform-hcl-standard/gcp-cloud/scripts/generate.py"},
                },
                "nodes": [{"provider": "aws"}],
                "testing_environment": {"provider": "aws"},
            },
        }
        self.write(self.template)

    def write(self, data, filename="ai-aggregator.yaml"):
        path = self.root / "topology" / data["metadata"]["environment"] / "selfhost" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data))
        return path

    def touch(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
        return path

    def select(self, environment="preview", provider="gcp", operation="plan", **kwargs):
        return resolve(self.root, environment, "single-node", provider, operation, **kwargs)

    def test_event_input_selects_cloud_independently_of_legacy_provider(self):
        outputs = self.select()
        self.assertEqual(outputs["provider"], "gcp")
        self.assertEqual(outputs["environment"], "preview")
        original = Path(outputs["template_path"]).read_text()
        materialize(outputs)
        rendered = yaml.safe_load(Path(outputs["manifest_path"]).read_text())
        self.assertEqual(rendered["spec"]["infrastructure"]["provider"], "gcp")
        self.assertEqual(rendered["spec"]["nodes"][0]["provider"], "gcp")
        self.assertEqual(rendered["spec"]["testing_environment"]["provider"], "gcp")
        self.assertEqual(Path(outputs["template_path"]).read_text(), original)

    def test_input_selects_other_resource_formats(self):
        for provider, renderer in (
            ("aws", "terraform-hcl-standard/aws-cloud/scripts/generate.py"),
            ("vps", "terraform-hcl-standard/vultr-cloud/scripts/generate.py"),
        ):
            with self.subTest(provider=provider):
                template = copy.deepcopy(self.template)
                template["spec"]["infrastructure"]["resource_contract"]["renderer"] = renderer
                self.write(template, f"ai-aggregator-{provider}.yaml")
                self.assertEqual(self.select(provider=provider)["provider"], provider)

    def test_environment_input_selects_its_own_template(self):
        template = copy.deepcopy(self.template)
        template["metadata"]["environment"] = "production-eu"
        self.write(template)
        outputs = self.select(environment="production-eu")
        self.assertIn("topology/production-eu/", outputs["template_path"])
        self.assertEqual(outputs["environment"], "production-eu")

    def test_missing_resource_format_cannot_fall_back_to_another_cloud(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.select(provider="vps")

    def test_missing_environment_cannot_fall_back_to_another_environment(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.select(environment="staging")

    def test_disabled_stage_and_activate_fail_before_materialization(self):
        for operation in ("stage", "activate"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "no resources will be created"):
                    self.select(operation=operation)
        self.assertFalse((self.root / ".runtime").exists())

    def test_disabled_plan_and_provision_remain_available(self):
        for operation in ("plan", "apply", "provision"):
            self.assertEqual(self.select(operation=operation)["deployment_enabled"], "false")

    def test_yaml_boolean_is_independent_of_indentation(self):
        template = copy.deepcopy(self.template)
        template["spec"]["enabled"] = True
        path = self.write(template)
        path.write_text(yaml.safe_dump(template, indent=4))
        self.assertEqual(self.select(operation="activate")["deployment_enabled"], "true")
        template["spec"]["enabled"] = "false"
        self.write(template)
        with self.assertRaisesRegex(ValueError, "YAML boolean"):
            self.select(operation="activate")

    def test_environment_cannot_escape_namespace(self):
        for environment in ("../prod", "prod\nprovider=aws", "", "UAT"):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ValueError, "lowercase name"):
                    self.select(environment=environment)

    def test_ambiguous_declarations_are_rejected(self):
        self.write(self.template, "ai-aggregator-copy.yaml")
        with self.assertRaisesRegex(ValueError, "found 2"):
            self.select()

    def test_existing_is_a_resource_mode_not_a_provider(self):
        with self.assertRaisesRegex(ValueError, "unsupported provider"):
            self.select(provider="existing", operation="plan")

    def test_akamai_handoff_selects_target_and_checks_hostname_domain(self):
        self.template["spec"].update(enabled=True, entrypoint={"domain": "ai-gateway.svc.plus"}, artifacts={
            "new_api": {"revision": "v1.2.3", "sha256": "a" * 64},
            "cliproxyapi": {"revision": "v4.5.6", "sha256": "b" * 64},
        }, apisix={"activation_validated": False})
        self.template["spec"]["infrastructure"].update(lifecycle="persistent")
        self.template["spec"]["infrastructure"]["resource_contract"] = {
            "renderer": "terraform-hcl-standard/akamai-cloud/scripts/generate.py",
            "workdir": "terraform-hcl-standard/akamai-cloud/envs/preview/gateway",
            "target_manifest": "iac/targets/preview-akamai.yaml",
            "account": "lab-account",
            "manifests": [{"path": "resources/example.net/preview/akamai/gateway.yaml", "workspace": "gateway",
                           "node": "gateway-01", "role": "gateway"}],
        }
        self.template["spec"]["nodes"] = [{"id": "gateway-01", "inventory_host": "ai-gateway.svc.plus", "ssh_user": "root", "role": "gateway"}]
        self.write(self.template)
        self.touch("iac/targets/preview-akamai.yaml")
        self.touch("resources/example.net/preview/akamai/gateway.yaml")
        result = self.select(provider="akamai-cloud", operation="stage",
                             target_hostname="ai-gateway.svc.plus", target_domain="ai-gateway.svc.plus",
                             resource_mode="existing")
        self.assertEqual(result["service_manifest"], "topology/preview/selfhost/ai-aggregator.yaml")
        self.assertEqual(result["iac_target_manifest"], "iac/targets/preview-akamai.yaml")
        self.assertEqual(result["resource_mode"], "existing")
        for field, value in (("target_hostname", "other.svc.plus"), ("target_domain", "other.svc.plus")):
            args = {"target_hostname": "ai-gateway.svc.plus", "target_domain": "ai-gateway.svc.plus"}
            args[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "exactly match"):
                self.select(provider="akamai-cloud", operation="plan", **args)

    def test_stage_and_activate_require_artifact_pins_and_acceptance(self):
        self.template["spec"].update(enabled=True, entrypoint={"domain": "gateway.example.net"},
            infrastructure={"provider": "akamai-cloud", "lifecycle": "persistent", "resource_contract": {
                "renderer": "terraform-hcl-standard/akamai-cloud/scripts/generate.py",
                "target_manifest": "iac/targets/preview-akamai.yaml", "account": "lab-account",
                "manifests": [{"path": "resources/example.net/preview/akamai/gateway.yaml", "workspace": "gateway",
                               "node": "gateway", "role": "gateway"}],
            }}, nodes=[{"id": "gateway", "inventory_host": "gateway.example.net", "ssh_user": "root", "role": "gateway"}],
            artifacts={}, apisix={"activation_validated": False})
        self.write(self.template)
        self.touch("iac/targets/preview-akamai.yaml")
        self.touch("resources/example.net/preview/akamai/gateway.yaml")
        with self.assertRaisesRegex(ValueError, "immutable version and SHA256"):
            self.select(provider="akamai-cloud", operation="stage", target_hostname="gateway.example.net",
                        target_domain="gateway.example.net")
        self.template["spec"]["artifacts"] = {name: {"revision": "v1.0.0", "sha256": "a" * 64}
                                                for name in ("new_api", "cliproxyapi")}
        self.write(self.template)
        with self.assertRaisesRegex(ValueError, "reviewed APISIX"):
            self.select(provider="akamai-cloud", operation="activate", target_hostname="gateway.example.net",
                        target_domain="gateway.example.net")

    def test_akamai_paths_and_state_follow_input_environment(self):
        infrastructure = self.template["spec"]["infrastructure"]
        self.template["spec"]["entrypoint"] = {"domain": "gateway.example.net"}
        self.template["spec"]["nodes"] = [{"id": "gateway", "inventory_host": "gateway.example.net", "ssh_user": "root", "role": "gateway"}]
        infrastructure["lifecycle"] = "persistent"
        infrastructure["resource_contract"] = {
            "renderer": "terraform-hcl-standard/akamai-cloud/scripts/generate.py",
            "workdir": "terraform-hcl-standard/akamai-cloud/envs/preview/gateway",
            "target_manifest": "iac/targets/preview-akamai.yaml",
            "account": "lab-account",
            "manifests": [{"path": "resources/example.net/preview/akamai/gateway.yaml", "workspace": "gateway",
                           "node": "gateway", "role": "gateway"}],
        }
        self.write(self.template)
        self.touch("iac/targets/preview-akamai.yaml")
        self.touch("resources/example.net/preview/akamai/gateway.yaml")
        outputs = self.select(provider="akamai-cloud", target_hostname="gateway.example.net", target_domain="gateway.example.net")
        self.assertEqual(outputs["account"], "lab-account")
        self.assertEqual(outputs["iac_target_manifest"], "iac/targets/preview-akamai.yaml")
        infrastructure["resource_contract"]["manifests"][0]["path"] = "resources/example.net/other/akamai/gateway.yaml"
        self.write(self.template)
        with self.assertRaisesRegex(ValueError, "selected environment"):
            self.select(provider="akamai-cloud", target_hostname="gateway.example.net", target_domain="gateway.example.net")


class WorkflowTests(unittest.TestCase):
    def test_environment_must_be_selected_as_uat_or_prod_input(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ai-aggregator-v1.yml").read_text())
        triggers = workflow.get("on") or workflow[True]
        environment = triggers["workflow_dispatch"]["inputs"]["environment"]
        self.assertEqual(environment["type"], "choice")
        self.assertEqual(environment["options"], ["uat", "prod"])
        self.assertNotIn("default", environment)

    def test_mutations_require_validation_and_use_event_provider(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ai-aggregator-v1.yml").read_text())
        for provider, job in (("aws", "aws-deploy"), ("gcp", "gcp-deploy"), ("vps", "vps-deploy"),
                              ("akamai-cloud", "akamai-deploy")):
            with self.subTest(job=job):
                declaration = workflow["jobs"][job]
                self.assertIn("validate", declaration["needs"])
                self.assertIn("resolve-provider", declaration["needs"])
                self.assertIn("github.event_name == 'workflow_dispatch'", declaration["if"])
                self.assertIn(f"outputs.provider == '{provider}'", declaration["if"])
                self.assertNotIn("outputs.deployment_environment", declaration["if"])

    def test_dispatch_preflight_is_folded_into_resolver_without_extra_job(self):
        from workflow_stage_depth_verify import longest_chain

        workflow = yaml.safe_load((ROOT / ".github/workflows/ai-aggregator-v1.yml").read_text())
        jobs = workflow["jobs"]
        self.assertNotIn("plan", jobs)
        self.assertIn("Validate selected declaration and Playbooks syntax", [
            step.get("name") for step in jobs["resolve-provider"]["steps"]
        ])
        self.assertEqual(len(longest_chain(jobs)), 4)

    def test_akamai_resource_handoff_stays_with_iac_and_playbooks_owners(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ai-aggregator-v1.yml").read_text())
        jobs = workflow["jobs"]
        self.assertEqual(jobs["iac-resources"]["uses"], "./.github/workflows/iac-orchestrator.yml")
        self.assertIn("resource_mode", jobs["iac-resources"]["with"])
        self.assertEqual(jobs["iac-resources"]["with"]["action"], "${{ inputs.operation == 'plan' && 'plan' || 'apply' }}")
        deploy = jobs["akamai-deploy"]
        self.assertIn("needs.iac-resources.outputs.result == 'applied_verified'", deploy["if"])
        actions = [step.get("uses", "") for step in deploy["steps"]]
        self.assertIn("./iac_modules/.github/actions/iac-receipt-verify", actions)
        self.assertIn("./iac_modules/.github/actions/iac-caller-inventory", actions)
        self.assertIn("./playbooks/.github/actions/ai-aggregator-deploy", actions)
        self.assertFalse(any("ansible-playbook" in str(step.get("run", "")) or
                             "terraform apply" in str(step.get("run", "")) for step in deploy["steps"]))
        self.assertNotIn("existing-deploy", jobs)
        inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
        self.assertNotIn("target_ip", inputs)


if __name__ == "__main__":
    unittest.main()
