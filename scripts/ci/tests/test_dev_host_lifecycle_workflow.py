"""The dev host lifecycle caller must stay pinned to the single disposable Dev target."""
from pathlib import Path
import unittest
import yaml

WF = Path(__file__).resolve().parents[3] / ".github/workflows/dev-host-lifecycle.yml"


class DevHostLifecycleWorkflow(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(WF.read_text())
        self.call = self.doc["jobs"]["iac"]["with"]

    def test_target_is_hard_coded_to_dev(self):
        self.assertEqual(self.call["environment"], "dev")
        self.assertEqual(self.call["target_manifest"], "iac/targets/dev-akamai-dev-k3s-v5.yaml")
        self.assertEqual(self.call["stage_scope"], "resources")
        self.assertIn('"namespace":"dev-k3s-v5"', self.call["selectors"])
        inputs = self.doc["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"operation", "confirm_target", "gitops_ref"})

    def test_no_prod_or_uat_reference(self):
        text = WF.read_text()
        for forbidden in ("web-saas-k3s-v5", "prod-akamai", "uat-akamai", "environment: prod", "environment: uat"):
            self.assertNotIn(forbidden, text)

    def test_iac_ref_is_full_sha_and_destructive_ops_need_confirmation(self):
        self.assertRegex(self.call["iac_ref"], r"^[0-9a-f]{40}$")
        script = self.doc["jobs"]["gate"]["steps"][0]["run"]
        self.assertIn('"$CONFIRM" != "dev-k3s-v5"', script)


if __name__ == "__main__":
    unittest.main()
