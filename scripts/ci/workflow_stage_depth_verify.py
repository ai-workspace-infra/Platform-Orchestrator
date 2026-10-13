#!/usr/bin/env python3
"""Limit workflow graph depth; matrix replicas count as one stage."""
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]


def longest_chain(jobs):
    paths = {}
    visiting = set()

    def visit(job):
        if job not in jobs:
            raise ValueError(f"unknown dependency: {job}")
        if job in visiting:
            raise ValueError(f"cyclic dependency: {job}")
        if job not in paths:
            visiting.add(job)
            needs = jobs[job].get("needs", [])
            if isinstance(needs, str):
                needs = [needs]
            if not isinstance(needs, list):
                raise ValueError(f"non-static needs: {job}")
            parent = max((visit(key) for key in needs), key=len, default=[])
            paths[job] = parent + [job]
            visiting.remove(job)
        return paths[job]

    return max((visit(key) for key in jobs), key=len, default=[])


def verify(root):
    config = json.loads((root / "scripts/ci/workflow-stage-depth-policy.json").read_text())
    limit = config["max_stages"]
    if limit != 5:
        raise ValueError("repository stage limit must remain 5")
    legacy = config["legacy"]
    errors = []
    files = sorted((root / ".github/workflows").glob("*.y*ml"))
    for path in files:
        data = yaml.safe_load(path.read_text())
        chain = longest_chain(data.get("jobs", {}))
        exception = legacy.get(path.name)
        ceiling = exception["max_stages"] if exception else limit
        if len(chain) > ceiling:
            errors.append(f"{path.name}: {len(chain)} stages > {ceiling}: {' -> '.join(chain)}")
        if exception and (len(chain) <= limit or len(chain) < ceiling):
            errors.append(f"{path.name}: remove or lower stale legacy ceiling")
        if exception and not exception.get("reason"):
            errors.append(f"{path.name}: legacy exception requires a reason")
        print(f"{path.name}: {len(chain)} stages" + (" (legacy debt)" if exception else ""))
    for name in legacy.keys() - {p.name for p in files}:
        errors.append(f"stale legacy workflow: {name}")
    if errors:
        raise ValueError("\n".join(errors))


if __name__ == "__main__":
    try:
        verify(ROOT)
    except (ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
