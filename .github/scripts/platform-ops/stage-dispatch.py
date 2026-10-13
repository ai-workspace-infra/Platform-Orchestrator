#!/usr/bin/env python3
"""Dispatch and wait for one correlated Selfhost stage run."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import quote


STAGES = {
    "resolve": "selfhost-stage-resolve.yml",
    "infra": "selfhost-stage-infra.yml",
    "deploy": "selfhost-stage-deploy.yml",
    "migrate": "selfhost-stage-migrate.yml",
    "verify": "selfhost-stage-verify.yml",
}
STAGE_CONTEXT_FIELDS = {
    "resolve": (),
    "infra": ("resolve_context", "resolve_run_id", "resolve_run_attempt"),
    "deploy": ("provision_context", "infra_run_id", "resolve_run_id", "resolve_run_attempt"),
    "migrate": ("provision_context", "deploy_context", "infra_run_id", "deploy_run_id"),
    "verify": ("provision_context", "deploy_context", "migration_context", "infra_run_id",
               "deploy_run_id", "migration_run_id"),
}
PRIOR_STAGE_CONTEXTS = {
    "resolve": (),
    "infra": (("resolve", "resolve_context", "resolve_run_id"),),
    "deploy": (("infra", "provision_context", "infra_run_id"),
               ("resolve", None, "resolve_run_id")),
    "migrate": (("infra", "provision_context", "infra_run_id"),
                ("deploy", "deploy_context", "deploy_run_id")),
    "verify": (("infra", "provision_context", "infra_run_id"),
               ("deploy", "deploy_context", "deploy_run_id"),
               ("migrate", "migration_context", "migration_run_id")),
}


def require_positive_decimal(value: str, label: str) -> str:
    if not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise SystemExit(f"{label} must be a positive decimal integer")
    return value


def gh(*args: str, payload: dict | None = None, timeout: int = 30):
    command = ["gh", "api", *args]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=True,
        env=os.environ.copy(),
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def find_child(repo: str, workflow: str, created: str, correlation: str):
    endpoint = (
        f"repos/{repo}/actions/workflows/{quote(workflow, safe='')}/runs"
        f"?event=workflow_dispatch&per_page=100&created=%3E%3D{quote(created, safe=':Z-')}"
    )
    runs = gh(endpoint).get("workflow_runs", [])
    matches = [run for run in runs if run.get("display_title") == f"Selfhost Stage {correlation}"]
    if len(matches) > 1:
        raise RuntimeError("More than one child run matched the stage correlation ID")
    return matches[0] if matches else None


def download_context(repo: str, run: dict, stage: str):
    # Verify is the terminal stage. Its outcome is the run conclusion itself;
    # unlike stages 1-4, it has no downstream contract artifact to return.
    if stage == "verify":
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"run_id={run['id']}\n")
                stream.write(f"run_attempt={run.get('run_attempt', 1)}\n")
                stream.write(f"run_url={run['html_url']}\n")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"Selfhost stage **{stage}**: [open child run]({run['html_url']})\n")
        print(f"Selfhost stage {stage}: {run['html_url']}", flush=True)
        return

    directory = Path(tempfile.mkdtemp(prefix=f"selfhost-{stage}-context-"))
    try:
        subprocess.run(
            ["gh", "run", "download", str(run["id"]), "--repo", repo,
             "--name", f"selfhost-stage-context-{stage}", "--dir", str(directory)],
            check=True,
            text=True,
            capture_output=True,
            timeout=60,
            env=os.environ.copy(),
        )
        path = directory / "stage-context.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("schema") != 1 or result.get("stage") != stage:
            raise RuntimeError("Child stage context does not match the requested stage")
        if str(result.get("run_id")) != str(run["id"]):
            raise RuntimeError("Child stage context run ID does not match the correlated run")
        context = result.get("context")
        if not isinstance(context, dict):
            raise RuntimeError("Child stage context is missing its result map")
        target = Path(os.environ["RUNNER_TEMP"]) / "selfhost-stage-result.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            delimiter = f"STAGE_CONTEXT_{run['id']}_{run.get('run_attempt', 1)}"
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"context<<{delimiter}\n")
                stream.write(json.dumps(context, separators=(",", ":")) + "\n")
                stream.write(f"{delimiter}\n")
                stream.write(f"run_id={run['id']}\n")
                stream.write(f"run_attempt={result['run_attempt']}\n")
                stream.write(f"run_url={run['html_url']}\n")
                stream.write(f"result_file={target}\n")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"Selfhost stage **{stage}**: [open child run]({run['html_url']})\n")
        print(f"Selfhost stage {stage}: {run['html_url']}", flush=True)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def download_parent_artifact(repo: str, parent_run_id: str, name: str, filename: str):
    directory = Path(tempfile.mkdtemp(prefix="selfhost-parent-gate-"))
    try:
        subprocess.run(
            ["gh", "run", "download", str(parent_run_id), "--repo", repo,
             "--name", name, "--dir", str(directory)],
            check=True,
            text=True,
            capture_output=True,
            timeout=60,
            env=os.environ.copy(),
        )
        return json.loads((directory / filename).read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def verify_parent():
    stage = os.environ["SELFHOST_STAGE"]
    if stage not in STAGES:
        raise SystemExit("SELFHOST_STAGE is not an approved stage")
    repo = os.environ["GITHUB_REPOSITORY"]
    parent_id = require_positive_decimal(os.environ["PARENT_RUN_ID"], "Parent run ID")
    attempt = require_positive_decimal(os.environ["PARENT_RUN_ATTEMPT"], "Parent run attempt")
    correlation = os.environ["CORRELATION_ID"]
    if correlation != f"{stage}-{parent_id}-{attempt}":
        raise SystemExit("Stage correlation does not match its parent run")
    parent = gh(f"repos/{repo}/actions/runs/{parent_id}")
    if not str(parent.get("path", "")).endswith(".github/workflows/selfhost-orchestrator.yml"):
        raise SystemExit("Stage parent is not Selfhost Orchestrator")
    if parent.get("status") != "in_progress" or str(parent.get("run_attempt")) != attempt:
        raise SystemExit("Stage parent is not the active requested run attempt")
    if parent.get("head_sha") != os.environ["GITHUB_SHA"]:
        raise SystemExit("Stage and parent control revisions do not match")
    if parent.get("head_branch") != os.environ["GITHUB_REF_NAME"]:
        raise SystemExit("Stage and parent refs do not match")

    request = json.loads(os.environ["SELFHOST_REQUEST_JSON"])
    attempt_suffix = os.environ["PARENT_RUN_ATTEMPT"]
    authorized_request = download_parent_artifact(repo, parent_id, f"selfhost-parent-request-{attempt_suffix}",
                                                   "selfhost-parent-request.json")
    if request != authorized_request:
        raise SystemExit("Stage request does not match the immutable parent request")

    contexts = json.loads(os.environ.get("SELFHOST_CONTEXTS_JSON", "{}"))
    for prior_stage, context_field, run_id_field in PRIOR_STAGE_CONTEXTS[stage]:
        result = download_parent_artifact(
            repo, parent_id, f"selfhost-parent-stage-{prior_stage}-{attempt_suffix}", "selfhost-stage-result.json")
        if result.get("schema") != 1 or result.get("stage") != prior_stage:
            raise SystemExit(f"Parent artifact for {prior_stage} is invalid")
        if run_id_field and str(contexts.get(run_id_field, "")) != str(result.get("run_id", "")):
            raise SystemExit(f"Stage run ID does not match the parent {prior_stage} result")
        if prior_stage == "resolve" and str(contexts.get("resolve_run_attempt", "")) != str(result.get("run_attempt", "")):
            raise SystemExit("Resolve run attempt does not match the parent result")
        if context_field and contexts.get(context_field) != json.dumps(result.get("context"), separators=(",", ":")):
            raise SystemExit(f"Stage context does not match the parent {prior_stage} result")
    print(f"Validated {stage} stage against active parent run {parent_id}", flush=True)


def main():
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "verify-parent":
        verify_parent()
        return
    stage = os.environ["SELFHOST_STAGE"]
    if stage not in STAGES:
        raise SystemExit("SELFHOST_STAGE is not an approved stage")
    repo = os.environ["GITHUB_REPOSITORY"]
    workflow = STAGES[stage]
    ref = os.environ["SELFHOST_STAGE_REF"]
    parent_run_id = os.environ["GITHUB_RUN_ID"]
    parent_attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    correlation = f"{stage}-{parent_run_id}-{parent_attempt}"
    request = json.loads(os.environ.get("SELFHOST_REQUEST_JSON", "{}"))
    if not isinstance(request, dict):
        raise SystemExit("Stage request must be a JSON object")
    contexts = {
        key: os.environ.get("SELFHOST_" + key.upper(), "")
        for key in STAGE_CONTEXT_FIELDS[stage]
    }
    if len(json.dumps(request)) > 60000 or len(json.dumps(contexts)) > 60000:
        raise SystemExit("Stage input exceeds the workflow_dispatch payload limit")

    inputs = {
        "payload_json": json.dumps(request, separators=(",", ":")),
        "parent_run_id": str(parent_run_id),
        "parent_run_attempt": str(parent_attempt),
        "correlation_id": correlation,
    }
    for key, value in contexts.items():
        if key not in {"resolve_context", "provision_context", "deploy_context", "migration_context",
                       "resolve_run_id", "resolve_run_attempt", "infra_run_id", "deploy_run_id", "migration_run_id"}:
            raise SystemExit(f"Unsupported context input for {stage}: {key}")
        inputs[key] = str(value)
    if len(json.dumps(inputs)) > 60000:
        raise SystemExit("Combined workflow_dispatch inputs exceed the safe payload limit")

    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state = {"run": None}
    interrupted = False

    def on_interrupt(signum, frame):
        nonlocal interrupted
        interrupted = True
        raise KeyboardInterrupt

    previous = {sig: signal.signal(sig, on_interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        # A POST timeout has an unknown outcome. Resolve by unique run name; never retry blindly.
        gh(
            "--method", "POST",
            f"repos/{repo}/actions/workflows/{workflow}/dispatches",
            "--input", "-",
            payload={"ref": ref, "inputs": inputs},
        )
        deadline = time.monotonic() + int(os.environ.get("SELFHOST_STAGE_TIMEOUT_SECONDS", "21000"))
        while time.monotonic() < deadline:
            if state["run"] is None:
                state["run"] = find_child(repo, workflow, created, correlation)
            else:
                state["run"] = gh(f"repos/{repo}/actions/runs/{state['run']['id']}")
            run = state["run"]
            if run and run.get("status") == "completed":
                if run.get("conclusion") != "success":
                    raise RuntimeError(f"Child stage failed: {run.get('html_url')} ({run.get('conclusion')})")
                download_context(repo, run, stage)
                return
            time.sleep(int(os.environ.get("SELFHOST_STAGE_POLL_SECONDS", "15")))
        raise TimeoutError(f"Child stage timed out: {correlation}")
    except BaseException:
        run = state.get("run")
        if run is None:
            try:
                run = find_child(repo, workflow, created, correlation)
                state["run"] = run
            except Exception:
                run = None
        if run and run.get("status") != "completed":
            try:
                gh("--method", "POST", f"repos/{repo}/actions/runs/{run['id']}/cancel", timeout=10)
            except Exception:
                print(f"::warning::Could not confirm cancellation for child run {run['id']}", flush=True)
        if interrupted:
            print(f"::warning::Parent interrupted; inspect child correlation {correlation} before retrying", flush=True)
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
