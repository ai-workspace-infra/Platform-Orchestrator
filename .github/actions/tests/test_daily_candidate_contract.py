from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/daily-main-snapshot.yaml"


class DailyCandidateContractTest(unittest.TestCase):
    expected_jobs = [
        "resolve-snapshot-tag",
        "snapshot",
        "snapshot-gate",
        "dispatch-environment",
        "snapshot-summary",
    ]

    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_five_stage_chain_and_owner_actions(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(list(jobs), self.expected_jobs)
        self.assertNotIn("needs", jobs["resolve-snapshot-tag"])
        self.assertEqual(jobs["snapshot"]["needs"], "resolve-snapshot-tag")
        self.assertEqual(jobs["snapshot-gate"]["needs"], ["resolve-snapshot-tag", "snapshot"])
        self.assertEqual(
            jobs["dispatch-environment"]["needs"],
            ["resolve-snapshot-tag", "snapshot-gate"],
        )
        self.assertEqual(jobs["snapshot-summary"]["needs"], self.expected_jobs[:4])

        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("uses: ./artifacts/.github/actions/component-candidate", source)
        self.assertIn("uses: ./.github/actions/candidate-gate", source)
        self.assertNotRegex(source, r"\.github/scripts/(snapshots|serverless)/")
        self.assertNotRegex(source, r"serverless-orchestrator|selfhost-orchestrator")
        self.assertNotRegex(source, r"refs/tags/v\*|production_eligible:\s*true")

    def test_candidate_gate_rejects_a_source_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            receipts = directory / "receipts"
            receipts.mkdir()
            receipt = {
                "component": "accounts",
                "candidate_id": "daily-build-2026.11.01-r1",
                "owner_sha": "b" * 40,
                "source_sha": "c" * 40,
                "status": "build_succeeded",
                "artifact_digest": f"sha256:{'d' * 64}",
                "artifact_assets": [],
            }
            (receipts / "accounts.json").write_text(json.dumps(receipt), encoding="utf-8")
            matrix = {
                "include": [
                    {
                        "name": "accounts",
                        "component": {
                            "name": "accounts",
                            "resolved_source_sha": "a" * 40,
                            "artifact": {"kind": "oci-image"},
                        },
                    }
                ]
            }
            output = directory / "output"
            environment = os.environ | {
                "CANDIDATE_ID": receipt["candidate_id"],
                "COMPONENT_MATRIX_JSON": json.dumps(matrix),
                "RECEIPTS_DIRECTORY": str(receipts),
                "DELIVERY_SCOPE": "web-saas",
                "GITOPS_SHA": "e" * 40,
                "ARTIFACTS_SHA": receipt["owner_sha"],
                "IAC_SHA": "f" * 40,
                "PLAYBOOKS_SHA": "1" * 40,
                "GITHUB_SHA": "2" * 40,
                "GITHUB_REPOSITORY": "ai-workspace-infra/Platform-Orchestrator",
                "GITHUB_RUN_ID": "1",
                "GITHUB_RUN_ATTEMPT": "1",
                "RUNNER_TEMP": str(directory),
                "GITHUB_OUTPUT": str(output),
            }
            process = subprocess.run(
                [sys.executable, str(ROOT / ".github/actions/candidate-gate/gate.py")],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("source SHA mismatch for accounts", process.stdout)

    def test_explicit_uat_dispatch_fails_closed_without_an_owner(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            policy = directory / "delivery/candidates/web-saas-uat.yaml"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                """
kind: ArtifactCandidatePolicy
spec:
  source_ref: main
  delivery_scope: web-saas
  candidate:
    id_prefix: daily-build
    immutable: true
    production_eligible: false
  components:
    - name: accounts
      source:
        repository: ai-workspace-services/accounts
  uat_dispatch:
    status: pending-owner
    target_ref: uat-serverless-web-saas
""".strip(),
                encoding="utf-8",
            )
            environment = os.environ | {
                "RESOLVE_MODE": "resolve",
                "GITOPS_ROOT": str(directory),
                "ARTIFACTS_ROOT": str(directory),
                "IAC_ROOT": str(directory),
                "PLAYBOOKS_ROOT": str(directory),
                "CANDIDATE_POLICY_PATH": "delivery/candidates/web-saas-uat.yaml",
                "SELECTED_SOURCE_REF": "main",
                "SELECTED_DELIVERY_SCOPE": "web-saas",
                "DEPLOY_AFTER_BUILD": "true",
                "SELECTED_TARGET_REF": "uat-serverless-web-saas",
                "GITHUB_TOKEN_INPUT": "not-used-before-the-gate",
                "GITHUB_OUTPUT": str(directory / "output"),
            }
            process = subprocess.run(
                [sys.executable, str(ROOT / ".github/actions/resolve-daily-candidate/resolve.py")],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("UAT dispatch owner is not ready in GitOps", process.stdout)


if __name__ == "__main__":
    unittest.main()
