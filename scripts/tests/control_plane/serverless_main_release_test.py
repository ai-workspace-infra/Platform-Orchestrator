import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[3] / ".github/scripts/snapshots/serverless-main-release.py"
SPEC = importlib.util.spec_from_file_location("serverless_main_release", SCRIPT)
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class MainReleaseTests(unittest.TestCase):
    def write_status(self, directory, mutate=None):
        path = Path(directory) / "services.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for index, repository in enumerate(RELEASE.REPOSITORIES):
                record = {
                    "repository": repository,
                    "status": "build_succeeded",
                    "tag": "daily-build-2026.10.27-r1",
                    "sha": f"{index + 1:040x}",
                }
                if mutate:
                    mutate(record, index)
                stream.write(json.dumps(record) + "\n")

    def test_scope_emits_exact_serverless_services(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                RELEASE.scope()
            self.assertEqual(output.read_text().strip(), "repositories=" + ",".join(RELEASE.REPOSITORIES))

    def test_snapshot_requires_every_successful_repo_and_same_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_status(directory)
            records = RELEASE.read_status(directory, "daily-build-2026.10.27-r1")
            self.assertEqual(set(records), set(RELEASE.REPOSITORIES))

            self.write_status(directory, lambda record, index: record.update(status="build_failed") if index == 0 else None)
            with self.assertRaisesRegex(ValueError, "did not pass"):
                RELEASE.read_status(directory, "daily-build-2026.10.27-r1")

            self.write_status(directory, lambda record, index: record.update(tag="daily-build-2026.10.27-r2") if index == 0 else None)
            with self.assertRaisesRegex(ValueError, "tag mismatch"):
                RELEASE.read_status(directory, "daily-build-2026.10.27-r1")

    def test_snapshot_rejects_missing_or_duplicate_source_records(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_status(directory)
            path = Path(directory) / "services.jsonl"
            lines = path.read_text().splitlines()
            path.write_text("\n".join(lines[:-1]) + "\n")
            with self.assertRaisesRegex(ValueError, "missing repositories"):
                RELEASE.read_status(directory, "daily-build-2026.10.27-r1")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(lines[0] + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                RELEASE.read_status(directory, "daily-build-2026.10.27-r1")

    def test_automatic_snapshot_tags_are_required(self):
        with patch.dict(os.environ, {"SNAPSHOT_TAG": "v2026.10.27"}, clear=False):
            with self.assertRaisesRegex(ValueError, "immutable daily snapshot tag"):
                RELEASE.verify()

    def test_verify_records_full_fixed_source_set_even_if_main_advances(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status"
            status.mkdir()
            self.write_status(status)
            output = Path(directory) / "release.json"
            output_file = Path(directory) / "github-output"
            gitops_sha = "a" * 40
            shas = {repository: f"{index + 1:040x}" for index, repository in enumerate(RELEASE.REPOSITORIES)}
            environment = {
                "SNAPSHOT_TAG": "daily-build-2026.10.27-r1",
                "SNAPSHOT_STATUS_DIRECTORY": str(status),
                "GITOPS_DIRECTORY": directory,
                "GITOPS_SHA": gitops_sha,
                "RELEASE_MANIFEST_OUTPUT": str(output),
                "GH_TOKEN": "test-service-token",
                "GH_GITOPS_TOKEN": "test-gitops-token",
                "GITHUB_OUTPUT": str(output_file),
            }
            with patch.dict(os.environ, environment), \
                    patch.object(RELEASE, "current_sha", side_effect=lambda repo, token, ref: gitops_sha if repo == "ai-workspace-infra/gitops" else shas[repo]), \
                    patch.object(RELEASE.subprocess, "run", return_value=type("Result", (), {"stdout": gitops_sha + "\n"})()):
                RELEASE.verify()
            manifest = json.loads(output.read_text())
            self.assertEqual(manifest["environment"], "uat")
            self.assertEqual([item["repository"] for item in manifest["services"]], list(RELEASE.REPOSITORIES))
            self.assertEqual(manifest["gitops"]["source_sha"], gitops_sha)
            self.assertEqual(manifest["website_content_ref"], manifest["snapshot_tag"])
            self.assertIn("source_fingerprint=" + manifest["source_fingerprint"], output_file.read_text())

            with patch.dict(os.environ, environment), \
                    patch.object(RELEASE, "current_sha", side_effect=lambda repo, token, ref: "b" * 40 if repo == RELEASE.REPOSITORIES[0] and ref == "main" else gitops_sha if repo == "ai-workspace-infra/gitops" else shas[repo]), \
                    patch.object(RELEASE.subprocess, "run", return_value=type("Result", (), {"stdout": gitops_sha + "\n"})()):
                RELEASE.verify()
            advanced_manifest = json.loads(output.read_text())
            self.assertEqual(advanced_manifest["services"][0]["source_sha"], shas[RELEASE.REPOSITORIES[0]])


if __name__ == "__main__":
    unittest.main()
