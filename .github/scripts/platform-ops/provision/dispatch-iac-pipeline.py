#!/usr/bin/env python3
"""Dispatch the standalone IaC workflow and bind its verified receipt to this caller."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


WORKFLOW = "iac-orchestrator.yml"
EXPECTED_RESULTS = {
    "check": "static_checked",
    "plan": "planned",
    "apply": "applied_verified",
    "destroy": "destroyed_verified",
}


def fail(message: str) -> None:
    raise SystemExit(f"::error::{message}")


def gh(*args: str, payload: dict | None = None, timeout: int = 30):
    command = ["gh", *args]
    data = json.dumps(payload) if payload is not None else None
    result = subprocess.run(command, input=data, text=True, capture_output=True,
                            check=False, timeout=timeout, env=os.environ.copy())
    if result.returncode:
        # GitHub CLI errors can include request details. Never print payloads or env.
        fail(f"GitHub API request failed while {args[0] if args else 'reading run state'} (exit {result.returncode}).")
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        fail("GitHub API returned malformed JSON.")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        fail(f"Missing required dispatcher input: {name}.")
    return value


def safe_ref(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", value)) and ".." not in value and not value.endswith("/")


def append_outputs(values: dict[str, object]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        fail("GITHUB_OUTPUT is unavailable.")
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            text = str(value)
            if "\n" in text or "\r" in text:
                fail(f"Unexpected multiline output: {key}.")
            stream.write(f"{key}={text}\n")


def main() -> int:
    repository = required("GITHUB_REPOSITORY")
    action = required("IAC_ACTION")
    environment = required("IAC_ENVIRONMENT")
    manifest = required("IAC_TARGET_MANIFEST")
    gitops_ref = required("IAC_GITOPS_REF")
    iac_ref = required("IAC_REF")
    scope = required("IAC_STAGE_SCOPE")
    bootstrap_mode = required("IAC_BOOTSTRAP_MODE")
    dispatch_ref = required("IAC_DISPATCH_REF")
    correlation = required("IAC_CORRELATION_ID")
    selectors_text = os.environ.get("IAC_SELECTORS", "{}")

    if environment == "prod-v2":
        environment = "prod"
    if action not in EXPECTED_RESULTS:
        fail("Unsupported IaC action.")
    if environment not in {"sit", "uat", "prod", "shared"}:
        fail("Unsupported IaC environment.")
    if scope not in {"all", "bootstrap", "account", "resources"}:
        fail("Unsupported IaC stage scope.")
    if bootstrap_mode not in {"verify", "reconcile"}:
        fail("Unsupported IaC bootstrap mode.")
    if not safe_ref(dispatch_ref):
        fail("IaC dispatch ref is not a safe branch or tag name.")
    if not re.fullmatch(r"[0-9a-f]{40}", gitops_ref) or not re.fullmatch(r"[0-9a-f]{40}", iac_ref):
        fail("IaC dispatch requires full GitOps and IaC commit SHAs.")
    try:
        selectors = json.loads(selectors_text)
    except json.JSONDecodeError:
        fail("IaC selectors are malformed JSON.")
    if not isinstance(selectors, dict):
        fail("IaC selectors must be a JSON object.")
    if selectors.get("environment") == "prod-v2":
        selectors["environment"] = "prod"

    expected = {
        "action": action,
        "environment": environment,
        "target_manifest": manifest,
        "gitops_ref": gitops_ref,
        "iac_ref": iac_ref,
        "stage_scope": scope,
        "bootstrap_mode": bootstrap_mode,
        "correlation_id": correlation,
        "selectors": json.dumps(selectors, separators=(",", ":")),
    }
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        gh("api", "--method", "POST",
           f"repos/{repository}/actions/workflows/{WORKFLOW}/dispatches",
           "--input", "-", payload={"ref": dispatch_ref, "inputs": expected})
    except SystemExit:
        # The POST may have reached GitHub even if the client lost its response.
        # Resolve the unique correlation before failing; never issue a second POST.
        print("::warning::IaC dispatch response is uncertain; resolving its correlation without redispatching.",
              flush=True)

    # workflow_dispatch has no response body. Correlation is carried in run-name;
    # never select a child solely by recency or retry the dispatch on lookup errors.
    child = None
    deadline = time.monotonic() + int(os.environ.get("IAC_WAIT_SECONDS", "7200"))
    while time.monotonic() < deadline and child is None:
        listing = gh("api", f"repos/{repository}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100&created=%3E%3D{started}")
        matches = [run for run in listing.get("workflow_runs", [])
                   if run.get("head_branch") == dispatch_ref
                   and run.get("event") == "workflow_dispatch"
                   and run.get("display_title") == f"iac:{correlation} / {action} / {environment}"]
        if len(matches) > 1:
            fail("Multiple IaC child runs matched the exact correlation; refusing to guess.")
        if matches:
            child = matches[0]
            break
        time.sleep(3)
    if child is None:
        fail("Could not resolve the correlated IaC child run; inspect GitHub Actions before retrying.")

    child_id = str(child["id"])
    run_deadline = time.monotonic() + int(os.environ.get("IAC_WAIT_SECONDS", "7200"))
    while time.monotonic() < run_deadline:
        current = gh("api", f"repos/{repository}/actions/runs/{child_id}")
        status = current.get("status")
        if status == "completed":
            if current.get("conclusion") != "success":
                fail(f"Correlated IaC workflow failed: {current.get('html_url', child_id)}.")
            child = current
            break
        if status not in {"queued", "in_progress", "waiting", "pending", "requested"}:
            fail(f"Correlated IaC workflow returned unexpected status {status!r}.")
        time.sleep(15)
    else:
        fail(f"Timed out waiting for IaC child {child_id}; do not redispatch before inspecting it.")

    attempt = int(child.get("run_attempt", 1))
    artifact_name = f"iac-summary-{child_id}-{attempt}"
    artifacts = gh("api", f"repos/{repository}/actions/runs/{child_id}/artifacts?per_page=100")
    matches = [item for item in artifacts.get("artifacts", [])
               if item.get("name") == artifact_name and not item.get("expired")]
    if len(matches) != 1:
        fail("Expected exactly one unexpired IaC summary artifact for the correlated run.")
    artifact_id = str(matches[0]["id"])

    download_dir = Path(required("RUNNER_TEMP")) / "iac-dispatch" / child_id
    download_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["gh", "run", "download", child_id, "--repo", repository,
                             "--name", artifact_name, "--dir", str(download_dir)],
                           text=True, capture_output=True, check=False, timeout=120,
                           env=os.environ.copy())
    if result.returncode:
        fail("Could not download the exact IaC receipt artifact.")
    summary_path = download_dir / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fail("The correlated IaC artifact is missing a valid summary.json.")

    context = summary.get("context", {})
    binding = {
        "run_id": child_id,
        "run_attempt": attempt,
        "action": action,
        "environment": environment,
        "manifest_path": manifest,
        "gitops_sha": gitops_ref,
        "iac_sha": iac_ref,
        "stage_scope": scope,
        "correlation_id": correlation,
    }
    for key, value in binding.items():
        actual = context.get(key)
        if key in {"run_id", "run_attempt"}:
            actual = str(actual)
            value = str(value)
        if actual != value:
            fail(f"IaC summary binding mismatch for {key}.")
    if summary.get("result") != EXPECTED_RESULTS[action]:
        fail("IaC summary result does not match the requested action.")

    append_outputs({
        "child_run_id": child_id,
        "child_run_attempt": attempt,
        "child_run_url": child.get("html_url", ""),
        "receipt_artifact_id": artifact_id,
        "receipt_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "gitops_sha": gitops_ref,
        "iac_sha": iac_ref,
        "result": summary["result"],
    })
    print(f"IaC child run {child_id} completed; correlated summary and artifact verified.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired:
        fail("A GitHub API request timed out; inspect the exact correlation before retrying.")
