#!/usr/bin/env python3
"""Select and freeze the complete Serverless UAT Main source combination."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


REPOSITORIES = (
    "ai-workspace-services/accounts",
    "ai-workspace-services/billing-service",
    "ai-workspace-services/content-service",
    "ai-workspace-services/portal",
    "ai-workspace-services/edge-gateway",
    "ai-workspace-services/frontend-router",
    "ai-workspace-services/postgresql",
)
BUILD_CONFIG = Path(__file__).resolve().parents[3] / ".github/daily-snapshot-builds.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh_json(token, endpoint):
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GH_TOKEN": token},
    )
    return json.loads(result.stdout)


def current_sha(repository, token, ref):
    response = gh_json(token, f"repos/{repository}/commits/{ref}")
    sha = response.get("sha")
    require(isinstance(sha, str) and len(sha) == 40, f"invalid commit identity for {repository}@{ref}")
    return sha


def validate_inventory():
    config = json.loads(BUILD_CONFIG.read_text(encoding="utf-8"))
    configured = tuple(sorted(
        item["repository"]
        for item in config.get("repositories", [])
        if item["repository"].startswith("ai-workspace-services/")
        and "uat" in item.get("environments", ["sit", "uat", "prod"])
    ))
    require(configured == tuple(sorted(REPOSITORIES)),
            "Serverless UAT snapshot allowlist differs from daily snapshot build inventory")


def read_status(directory, snapshot_tag):
    records = {}
    for path in Path(directory).glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            repository = record.get("repository")
            if repository in REPOSITORIES:
                require(repository not in records, f"duplicate snapshot status for {repository}")
                require(record.get("status") == "build_succeeded", f"snapshot build did not pass for {repository}")
                require(record.get("tag") == snapshot_tag, f"snapshot tag mismatch for {repository}")
                require(isinstance(record.get("sha"), str) and len(record["sha"]) == 40,
                        f"missing full source SHA for {repository}")
                records[repository] = record
    missing = sorted(set(REPOSITORIES) - set(records))
    require(not missing, f"snapshot evidence missing repositories: {', '.join(missing)}")
    return records


def scope():
    validate_inventory()
    output = os.environ.get("GITHUB_OUTPUT")
    require(output, "GITHUB_OUTPUT is required")
    with open(output, "a", encoding="utf-8") as stream:
        stream.write(f"repositories={','.join(REPOSITORIES)}\n")


def verify():
    validate_inventory()
    snapshot_tag = os.environ.get("SNAPSHOT_TAG", "")
    require(snapshot_tag.startswith("daily-build-") or snapshot_tag.startswith("uat-daily-build-"),
            "automatic Serverless release requires an immutable daily snapshot tag")
    status_directory = os.environ["SNAPSHOT_STATUS_DIRECTORY"]
    gitops_directory = Path(os.environ["GITOPS_DIRECTORY"])
    gitops_sha = os.environ["GITOPS_SHA"]
    output_path = os.environ["RELEASE_MANIFEST_OUTPUT"]
    service_token = os.environ["GH_TOKEN"]
    gitops_token = os.environ["GH_GITOPS_TOKEN"]

    records = read_status(status_directory, snapshot_tag)
    gitops_checkout_sha = subprocess.run(
        ["git", "-C", str(gitops_directory), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    require(gitops_checkout_sha == gitops_sha and len(gitops_sha) == 40,
            "GitOps checkout does not match the resolved dispatch revision")
    require(current_sha("ai-workspace-infra/gitops", gitops_token, "main") == gitops_sha,
            "GitOps main advanced before UAT dispatch")

    frozen = []
    for repository in REPOSITORIES:
        recorded_sha = records[repository]["sha"]
        require(current_sha(repository, service_token, snapshot_tag) == recorded_sha,
                f"immutable snapshot ref mismatch for {repository}")
        frozen.append({"repository": repository, "source_sha": recorded_sha, "snapshot_ref": snapshot_tag})

    manifest = {
        "format": "serverless-main-release/v1",
        "environment": "uat",
        "deployment_owner": "serverless-orchestrator.yml",
        "snapshot_tag": snapshot_tag,
        "website_content_ref": snapshot_tag,
        "gitops": {"repository": "ai-workspace-infra/gitops", "source_sha": gitops_sha},
        "services": frozen,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["source_fingerprint"] = hashlib.sha256(canonical).hexdigest()
    Path(output_path).write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"source_fingerprint={manifest['source_fingerprint']}\n")
        stream.write(f"website_content_ref={snapshot_tag}\n")


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in {"scope", "verify"}, "usage: serverless-main-release.py scope|verify")
    {"scope": scope, "verify": verify}[sys.argv[1]]()


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, json.JSONDecodeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(2)
