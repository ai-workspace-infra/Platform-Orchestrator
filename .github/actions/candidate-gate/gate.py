#!/usr/bin/env python3
"""Validate component receipts and emit one immutable candidate manifest."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def output(name: str, value: str) -> None:
    with open(required("GITHUB_OUTPUT"), "a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def main() -> None:
    candidate_id = required("CANDIDATE_ID")
    matrix = json.loads(required("COMPONENT_MATRIX_JSON"))
    expected = {entry["name"]: entry["component"] for entry in matrix["include"]}
    receipt_paths = sorted(Path(required("RECEIPTS_DIRECTORY")).rglob("*.json"))
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in receipt_paths]
    actual_names = [receipt["component"] for receipt in receipts]
    if len(set(actual_names)) != len(actual_names):
        raise RuntimeError("duplicate component receipts")
    missing = sorted(set(expected) - set(actual_names))
    unexpected = sorted(set(actual_names) - set(expected))
    if missing:
        raise RuntimeError(f"missing component receipts: {', '.join(missing)}")
    if unexpected:
        raise RuntimeError(f"unexpected component receipts: {', '.join(unexpected)}")

    artifacts_sha = required("ARTIFACTS_SHA")
    for receipt in receipts:
        name = receipt["component"]
        component = expected[name]
        if receipt["candidate_id"] != candidate_id:
            raise RuntimeError(f"candidate mismatch for {name}")
        if receipt["owner_sha"] != artifacts_sha:
            raise RuntimeError(f"owner SHA mismatch for {name}")
        if receipt["source_sha"] != component["resolved_source_sha"]:
            raise RuntimeError(f"source SHA mismatch for {name}")
        if receipt["status"] != "build_succeeded":
            raise RuntimeError(f"build failed for {name}")
        artifact = component["artifact"]
        if artifact["kind"] == "oci-image":
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.get("artifact_digest", "")):
                raise RuntimeError(f"missing OCI digest for {name}")
        elif artifact["kind"] == "github-release":
            missing_assets = sorted(
                set(artifact["required_assets"]) - set(receipt.get("artifact_assets", []))
            )
            if missing_assets:
                raise RuntimeError(f"missing release assets for {name}: {', '.join(missing_assets)}")
        else:
            raise RuntimeError(f"unsupported artifact kind for {name}")

    manifest = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "environment": "uat",
        "production_eligible": False,
        "delivery_scope": required("DELIVERY_SCOPE"),
        "owners": {
            "orchestrator_sha": required("GITHUB_SHA"),
            "gitops_sha": required("GITOPS_SHA"),
            "artifacts_sha": artifacts_sha,
            "iac_sha": required("IAC_SHA"),
            "playbooks_sha": required("PLAYBOOKS_SHA"),
        },
        "build_run": {
            "repository": required("GITHUB_REPOSITORY"),
            "run_id": required("GITHUB_RUN_ID"),
            "run_attempt": required("GITHUB_RUN_ATTEMPT"),
        },
        "components": sorted(receipts, key=lambda receipt: receipt["component"]),
    }
    canonical = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    manifest["fingerprint"] = fingerprint
    directory = Path(required("RUNNER_TEMP"), "daily-candidate")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "candidate-manifest.json"
    path.write_text(f"{json.dumps(manifest, indent=2, sort_keys=True)}\n", encoding="utf-8")
    output("manifest_path", str(path))
    output("fingerprint", fingerprint)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(f"::error::{error}")
        raise SystemExit(1) from error
