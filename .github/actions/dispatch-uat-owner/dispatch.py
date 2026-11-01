#!/usr/bin/env python3
"""Dispatch one fixed UAT owner run and validate its receipt."""

from __future__ import annotations

import io
import calendar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def api(route: str, token: str, method: str = "GET", body: dict | None = None, raw: bool = False):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}{route}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            if raw:
                return payload
            return None if not payload else json.loads(payload)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub API {method} {route} failed ({error.code})") from error


def optional_get(route: str, token: str) -> dict | None:
    try:
        return api(route, token)
    except RuntimeError as error:
        if "failed (404)" in str(error):
            return None
        raise


def output(name: str, value: object) -> None:
    with open(required("GITHUB_OUTPUT"), "a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def extract_receipt(archive: bytes, directory: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for member in bundle.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError("UAT receipt artifact contains an unsafe path")
        bundle.extractall(directory)
    receipts = sorted(directory.rglob("*.json"))
    if len(receipts) != 1:
        raise RuntimeError("UAT receipt artifact must contain exactly one JSON receipt")
    return receipts[0]


def main() -> None:
    config = json.loads(required("UAT_DISPATCH_JSON"))
    if config.get("status") != "ready":
        raise RuntimeError("UAT owner declaration is not ready")
    for key in ("owner_key", "owner_repository", "owner_workflow", "receipt_artifact", "target_ref"):
        if not config.get(key):
            raise RuntimeError(f"UAT owner declaration is missing {key}")
    manifest = json.loads(Path(required("CANDIDATE_MANIFEST")).read_text(encoding="utf-8"))
    if manifest.get("fingerprint") != required("CANDIDATE_FINGERPRINT"):
        raise RuntimeError("candidate fingerprint mismatch")
    owner_sha = manifest.get("owners", {}).get(f"{config['owner_key']}_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", owner_sha):
        raise RuntimeError("UAT owner key is not backed by a pinned candidate SHA")

    token = required("GITHUB_TOKEN_INPUT")
    repository = config["owner_repository"]
    commit = api(f"/repos/{repository}/commits/{owner_sha}", token)
    if commit["sha"] != owner_sha:
        raise RuntimeError("UAT owner repository does not contain the pinned candidate SHA")
    tag = f"{manifest['candidate_id']}-uat-owner"
    encoded_tag = urllib.parse.quote(tag, safe="")
    existing = optional_get(f"/repos/{repository}/git/ref/tags/{encoded_tag}", token)
    if existing and existing["object"]["sha"] != owner_sha:
        raise RuntimeError("UAT owner tag points to a different SHA")
    if not existing:
        api(
            f"/repos/{repository}/git/refs",
            token,
            "POST",
            {"ref": f"refs/tags/{tag}", "sha": owner_sha},
        )

    started = time.time()
    api(
        f"/repos/{repository}/actions/workflows/{urllib.parse.quote(config['owner_workflow'], safe='')}/dispatches",
        token,
        "POST",
        {
            "ref": tag,
            "inputs": {
                "candidate_id": manifest["candidate_id"],
                "candidate_fingerprint": manifest["fingerprint"],
                "delivery_scope": manifest["delivery_scope"],
                "target_ref": config["target_ref"],
            },
        },
    )
    timeout = int(os.environ.get("UAT_OWNER_TIMEOUT_SECONDS", "3600"))
    run = None
    workflow = urllib.parse.quote(config["owner_workflow"], safe="")
    while time.time() - started < timeout:
        route = (
            f"/repos/{repository}/actions/workflows/{workflow}/runs"
            f"?branch={encoded_tag}&event=workflow_dispatch&per_page=20"
        )
        runs = api(route, token)["workflow_runs"]
        candidates = [
            item
            for item in runs
            if item["head_sha"] == owner_sha
            and calendar.timegm(time.strptime(item["created_at"], "%Y-%m-%dT%H:%M:%SZ")) >= started - 5
        ]
        run = max(candidates, key=lambda item: item["id"], default=None)
        if not run or run["status"] != "completed":
            time.sleep(10)
            continue
        if run["conclusion"] != "success":
            raise RuntimeError(f"UAT owner run {run['html_url']} concluded {run['conclusion']}")
        break
    if not run or run["status"] != "completed":
        raise RuntimeError("timed out waiting for the UAT owner run")

    artifacts = api(f"/repos/{repository}/actions/runs/{run['id']}/artifacts", token)["artifacts"]
    matches = [
        artifact
        for artifact in artifacts
        if artifact["name"] == config["receipt_artifact"] and not artifact["expired"]
    ]
    if len(matches) != 1:
        raise RuntimeError("declared UAT receipt artifact is missing or ambiguous")
    archive = api(
        f"/repos/{repository}/actions/artifacts/{matches[0]['id']}/zip", token, raw=True
    )
    directory = Path(required("RUNNER_TEMP"), f"uat-owner-receipt-{run['id']}")
    directory.mkdir(parents=True, exist_ok=False)
    receipt_path = extract_receipt(archive, directory)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        receipt.get("candidate_id") != manifest["candidate_id"]
        or receipt.get("candidate_fingerprint") != manifest["fingerprint"]
        or receipt.get("status") != "success"
    ):
        raise RuntimeError("UAT owner receipt does not match the fixed candidate")
    output("receipt_path", receipt_path)
    output("run_id", run["id"])
    output("run_attempt", run["run_attempt"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(f"::error::{error}")
        raise SystemExit(1) from error
