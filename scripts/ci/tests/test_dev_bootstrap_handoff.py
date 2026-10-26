"""Offline integration through the actual IaC summary and Playbooks contracts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HANDOFF = load("dev_handoff", ROOT / ".github/actions/dev-bootstrap-handoff/handoff.py")


class Workflow(unittest.TestCase):
    def test_create_only_hard_dag_and_fixed_owners(self):
        jobs = yaml.safe_load((ROOT / ".github/workflows/dev-host-lifecycle.yml").read_text())["jobs"]
        self.assertIn("inputs.operation == 'create'", jobs["bootstrap"]["if"])
        self.assertIn("needs.iac.result == 'success'", jobs["bootstrap"]["if"])
        self.assertIn("needs.gate.result == 'success'", jobs["bootstrap"]["if"])
        self.assertEqual(jobs["iac"]["with"]["dev_bootstrap_handoff"], "${{ inputs.operation == 'create' }}")
        self.assertRegex(jobs["bootstrap"]["uses"], r"dev-k3s-bootstrap.yml@[0-9a-f]{40}$")
        self.assertEqual(set(jobs), {"gate", "iac", "bootstrap"})
        owner = yaml.safe_load((ROOT / ".github/workflows/iac-orchestrator.yml").read_text())
        summary = owner["jobs"]["summary"]["steps"]
        verify_index = next(i for i,s in enumerate(summary) if s.get("uses") == "./iac_modules/.github/actions/iac-receipt-verify")
        select_index = next(i for i,s in enumerate(summary) if s.get("id") == "select")
        self.assertLess(verify_index, select_index)
        for step in summary[verify_index:]:
            self.assertEqual(step["if"], "inputs.dev_bootstrap_handoff")
        depth = load("stage_depth", ROOT / "scripts/ci/workflow_stage_depth_verify.py")
        # This caller fixes scope=resources: bootstrap/account/destroy jobs
        # are existing unselected branches, never executed create stages.
        self.assertEqual(jobs["iac"]["with"]["stage_scope"], "resources")
        active = {name: copy.deepcopy(owner["jobs"][name]) for name in ("prepare", "resources", "summary")}
        for job in active.values():
            needs = job.get("needs", [])
            if isinstance(needs, str):
                needs = [needs]
            job["needs"] = [name for name in needs if name in active]
        self.assertLessEqual(2 + len(depth.longest_chain(active)), 5)



class ActualProducerBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        owner = os.environ.get("IAC_TEST_ROOT")
        playbooks = os.environ.get("PLAYBOOKS_TEST_ROOT")
        if not owner or not playbooks:
            raise unittest.SkipTest("actual immutable producers are required; dedicated CI supplies both")
        owner = Path(owner).resolve()
        sys.path.insert(0, str(owner / "scripts/pipeline"))
        cls.catalog_tests = load("actual_catalog_fixtures", owner / "scripts/pipeline/tests/test_iac_target_catalog.py")
        from unified.evidence import sanitize_inventory, summarize, receipt_base, verify_summary
        from unified.contracts import write_json, digest
        cls.api = dict(sanitize=sanitize_inventory, summarize=summarize, receipt_base=receipt_base, verify=verify_summary, write=write_json, digest=digest)
        cls.adapter = load("actual_playbooks_adapter", Path(playbooks).resolve() / "scripts/dev_k3s_bootstrap.py")

    def setUp(self):
        self.fixture = self.catalog_tests.CatalogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        target = self.fixture.dev_target(HANDOFF.HOST)
        target.update(id=HANDOFF.TARGET_ID, project="svc.plus", account="manbuzhe2026")
        target["stages"]["resources"]["state"]["key"] = HANDOFF.STATE
        self.fixture.publish_dev(target)
        self.context = self.fixture.dev_context("apply")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = {HANDOFF.HOST: {"name": HANDOFF.HOST, "label": HANDOFF.HOST, "instance_id": 123, "ip": "198.51.100.10", "groups": ["dev", "k3s"], "host_vars": {
            "cloud_provider": "akamai-cloud", "cloud_region": "jp-tyo-3", "k3s_platform_node_name": HANDOFF.HOST,
            "k3s_platform_k3s_version": "v1.37.1+k3s1", "k3s_platform_write_kubeconfig_mode": "0600"}}}
        self.cmdb = self.api["sanitize"](raw)
        evidence = self.root / "stage"
        self.api["write"](evidence / "inventory.json", self.cmdb)
        receipt = self.api["receipt_base"](self.context, self.context["targets"][0], "resources")
        receipt.update(result="applied_verified", plan_sha256="a"*64, inventory_sha256=self.api["digest"](evidence / "inventory.json"), verification={k: True for k in ("identity", "contract", "cleanup", "ownership", "convergence")})
        self.api["write"](evidence / "receipt.json", receipt)
        needs = {"prepare": {"result": "success"}, "resources": {"result": "success"}, **{k: {"result": "skipped"} for k in ("bootstrap", "account", "destroy-bootstrap", "destroy-account", "destroy-resources")}}
        self.destination = self.root / "bundle"
        self.summary = self.api["summarize"](self.context, evidence, needs, self.destination)
        self.inventories = json.loads((self.destination / "inventory.json").read_text())

    def test_actual_owner_bundle_verifies_and_reaches_actual_wrapper_contract(self):
        c = self.context
        self.api["verify"](self.destination / "summary.json", self.api["digest"](self.destination / "summary.json"), c["run_id"], c["run_attempt"], c["gitops_sha"], c["iac_sha"], c["manifest_path"], "apply", c["correlation_id"])
        raw, instance = HANDOFF.select(self.summary, self.inventories, self.summary["deploy_matrix"])
        self.assertEqual(json.loads(raw), self.cmdb)
        self.adapter.validate_cmdb(json.loads(raw), instance)

    def test_plan_extra_target_missing_runtime_and_wrong_matrix_fail(self):
        for key, value in (("result", "planned"), ("deploy_matrix", [])):
            summary = copy.deepcopy(self.summary)
            summary[key] = value
            with self.assertRaises(ValueError):
                HANDOFF.select(summary, self.inventories, self.summary["deploy_matrix"])
        for inventories in ({}, {**self.inventories, "other": {}}):
            with self.assertRaises(ValueError):
                HANDOFF.select(self.summary, inventories, self.summary["deploy_matrix"])
        inventory = copy.deepcopy(self.inventories)
        inventory[HANDOFF.TARGET_ID][HANDOFF.HOST].pop("instance_id")
        with self.assertRaises(ValueError):
            HANDOFF.select(self.summary, inventory, self.summary["deploy_matrix"])

    def test_owner_checksum_tampering_and_failed_cleanup_are_not_accepted(self):
        c = self.context
        with self.assertRaises(ValueError):
            self.api["verify"](self.destination / "summary.json", "0"*64, c["run_id"], c["run_attempt"], c["gitops_sha"], c["iac_sha"], c["manifest_path"], "apply", c["correlation_id"])
        self.summary["receipts"][0]["verification"]["cleanup"] = False
        self.api["write"](self.destination / "summary.json", self.summary)
        with self.assertRaises(ValueError):
            self.api["verify"](self.destination / "summary.json", self.api["digest"](self.destination / "summary.json"), c["run_id"], c["run_attempt"], c["gitops_sha"], c["iac_sha"], c["manifest_path"], "apply", c["correlation_id"])


if __name__ == "__main__":
    unittest.main()
