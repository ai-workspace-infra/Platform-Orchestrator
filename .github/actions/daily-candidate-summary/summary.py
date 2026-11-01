#!/usr/bin/env python3
"""Write and enforce the final Daily candidate status."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def write_output(name: str, value: object) -> None:
    with open(required("GITHUB_OUTPUT"), "a", encoding="utf-8") as stream:
        stream.write(f"{name}={str(value).lower() if isinstance(value, bool) else value}\n")


def write_summary() -> None:
    deploy = required("DEPLOY_REQUESTED") == "true"
    results = {
        "prepare": required("PREPARE_RESULT"),
        "build": required("BUILD_RESULT"),
        "gate": required("GATE_RESULT"),
        "dispatch": required("DISPATCH_RESULT"),
    }
    accepted = all(results[name] == "success" for name in ("prepare", "build", "gate"))
    accepted = accepted and results["dispatch"] == ("success" if deploy else "skipped")
    summary = {
        "schema_version": 1,
        "candidate_id": os.environ.get("CANDIDATE_ID", ""),
        "candidate_fingerprint": os.environ.get("CANDIDATE_FINGERPRINT", ""),
        "deploy_requested": deploy,
        "results": results,
        "accepted": accepted,
        "statement": (
            "fixed candidate build and explicit UAT owner dispatch"
            if deploy
            else "fixed candidate build only"
        ),
    }
    directory = Path(required("RUNNER_TEMP"), "daily-candidate-summary")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "summary.json"
    path.write_text(f"{json.dumps(summary, indent=2, sort_keys=True)}\n", encoding="utf-8")
    with open(required("GITHUB_STEP_SUMMARY"), "a", encoding="utf-8") as stream:
        stream.write("## Daily candidate\n\n")
        stream.write(f"- Candidate: `{summary['candidate_id']}`\n")
        stream.write(f"- Fingerprint: `{summary['candidate_fingerprint']}`\n")
        stream.write(f"- Scope: {summary['statement']}\n")
        for stage, result in results.items():
            stream.write(f"- {stage}: `{result}`\n")
        stream.write(f"- Final: **{'accepted' if accepted else 'rejected'}**\n")
    write_output("summary_path", path)
    write_output("accepted", accepted)


def main() -> None:
    mode = sys.argv[1]
    if mode == "write":
        write_summary()
    elif mode == "enforce":
        if os.environ.get("ACCEPTED", "false") != "true":
            raise RuntimeError("Daily candidate run is incomplete or failed")
    else:
        raise RuntimeError("mode must be write or enforce")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print(f"::error::{error}")
        raise SystemExit(1) from error
