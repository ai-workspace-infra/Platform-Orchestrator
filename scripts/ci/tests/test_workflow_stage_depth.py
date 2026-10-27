#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
from contextlib import redirect_stdout
import io

import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("stage_depth", ROOT / "scripts/ci/workflow_stage_depth_verify.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class GraphTests(unittest.TestCase):
    def test_matrix_and_parallel_jobs_do_not_add_depth(self):
        jobs = {"a": {}, "b": {"needs": "a", "strategy": {"matrix": {"org": [1, 2, 3]}}},
                "c": {"needs": "a"}, "d": {"needs": ["b", "c"]}}
        self.assertEqual(len(checker.longest_chain(jobs)), 3)

    def test_cycles_and_missing_dependencies_fail(self):
        for jobs in ({"a": {"needs": "b"}}, {"a": {"needs": "b"}, "b": {"needs": "a"}}):
            with self.assertRaises(ValueError):
                checker.longest_chain(jobs)

    def test_six_sequential_jobs_exceed_limit(self):
        jobs = {str(i): {"needs": str(i-1)} if i else {} for i in range(6)}
        self.assertGreater(len(checker.longest_chain(jobs)), 5)

    def test_policy_rejects_new_long_chain_and_stale_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts/ci").mkdir(parents=True)
            (root / ".github/workflows").mkdir(parents=True)
            policy = root / "scripts/ci/workflow-stage-depth-policy.json"
            workflow = root / ".github/workflows/example.yml"
            jobs = {str(i): {"needs": str(i-1)} if i else {} for i in range(6)}
            workflow.write_text(yaml.safe_dump({"jobs": jobs}))
            policy.write_text(json.dumps({"max_stages": 5, "legacy": {}}))
            with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "6 stages > 5"):
                checker.verify(root)
            policy.write_text(json.dumps({"max_stages": 5, "legacy": {"example.yml": {"max_stages": 6, "reason": "existing debt"}}}))
            with redirect_stdout(io.StringIO()):
                checker.verify(root)
            del jobs["5"]
            workflow.write_text(yaml.safe_dump({"jobs": jobs}))
            with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "stale legacy ceiling"):
                checker.verify(root)

    def test_daily_gate_keeps_order_and_dispatch_inputs(self):
        document = yaml.safe_load((ROOT / ".github/workflows/daily-main-snapshot.yaml").read_text())
        jobs = document["jobs"]
        trigger = document.get('on', document.get(True))
        deployment = trigger['workflow_dispatch']['inputs']['deploy_after_build']
        self.assertEqual(deployment['type'], 'boolean')
        self.assertIs(deployment['default'], False)
        self.assertEqual(len(jobs), 5)
        self.assertEqual(len(checker.longest_chain(jobs)), 5)
        gate = jobs["snapshot-gate"]
        steps = gate["steps"]
        resolve = next(i for i, s in enumerate(steps) if s.get("id") == "resolve")
        readiness = next(i for i, s in enumerate(steps) if s.get("with", {}).get("operation") == "shared-readiness")
        select = next(i for i, s in enumerate(steps) if s.get("id") == "select")
        self.assertLess(resolve, readiness)
        self.assertLess(readiness, select)
        self.assertIn("(inputs.repositories || '') == ''", gate["if"])
        dispatch = jobs["dispatch-environment"]
        self.assertEqual(dispatch["needs"], "snapshot-gate")
        self.assertIn("needs.snapshot-gate.result == 'success'", dispatch["if"])
        self.assertIn("inputs.deploy_after_build == true", dispatch['if'])
        automatic_or_requested = "${{ (github.event_name != 'workflow_dispatch' || inputs.deploy_after_build == true) }}"
        self.assertEqual(steps[readiness]['if'], automatic_or_requested)
        self.assertEqual(steps[select]['if'], automatic_or_requested)
        self.assertIn("needs.snapshot-gate.outputs.matrix", dispatch["strategy"]["matrix"])
        self.assertIn("always()", jobs["snapshot-summary"]["if"])
        failure = jobs["snapshot-summary"]["steps"][-1]["if"]
        self.assertIn("needs.snapshot-gate.result != 'success'", failure)
        self.assertIn("needs.dispatch-environment.result != 'success'", failure)
        self.assertIn("(github.event_name != 'workflow_dispatch' || inputs.deploy_after_build == true) && needs.dispatch-environment.result != 'success'", failure)

        prepare_vault = next(s for s in jobs["resolve-snapshot-tag"]["steps"] if s.get("id") == "vault")
        self.assertIn("github-actions-platform-ops-toolkit-prod-release", prepare_vault["with"]["role"])
        build_vault = next(s for s in jobs["snapshot"]["steps"] if s.get("id") == "vault")
        self.assertIn("github-actions-platform-ops-toolkit-prod-release", build_vault["with"]["role"])
        dispatch_vault = next(s for s in jobs["dispatch-environment"]["steps"] if s.get("id") == "vault")
        self.assertIn("github-actions-platform-ops-toolkit-prod-release", dispatch_vault["with"]["role"])


if __name__ == "__main__":
    unittest.main()
