#!/usr/bin/env python3
"""Resolve one reviewed Daily candidate policy without executing an owner."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import yaml


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def output(name: str, value: object) -> None:
    rendered = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    with open(required("GITHUB_OUTPUT"), "a", encoding="utf-8") as stream:
        if "\n" in rendered:
            delimiter = f"gha_{uuid.uuid4().hex}"
            stream.write(f"{name}<<{delimiter}\n{rendered}\n{delimiter}\n")
        else:
            stream.write(f"{name}={rendered}\n")


def repository_sha(root: str) -> str:
    sha = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"invalid repository SHA for {root}")
    return sha


def github(path: str, token: str, allow_not_found: bool = False) -> dict | None:
    request = urllib.request.Request(
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if allow_not_found and error.code == 404:
            return None
        raise RuntimeError(f"GitHub API GET {path} failed ({error.code})") from error


def load_contract() -> tuple[dict, str, str, list[dict]]:
    gitops_root = required("GITOPS_ROOT")
    scope = required("SELECTED_DELIVERY_SCOPE")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", scope):
        raise RuntimeError("delivery_scope is invalid")
    expected_path = f"delivery/candidates/{scope}-uat.yaml"
    if required("CANDIDATE_POLICY_PATH") != expected_path:
        raise RuntimeError(f"candidate policy path must be {expected_path}")
    policy = yaml.safe_load(Path(gitops_root, expected_path).read_text(encoding="utf-8"))
    if policy.get("kind") != "ArtifactCandidatePolicy":
        raise RuntimeError("unsupported candidate policy")
    spec = policy["spec"]
    source_ref = required("SELECTED_SOURCE_REF")
    if source_ref != spec["source_ref"]:
        raise RuntimeError("Daily candidate source_ref must match the reviewed policy")
    if scope != spec["delivery_scope"]:
        raise RuntimeError("delivery_scope does not match the reviewed policy")
    candidate = spec["candidate"]
    if candidate.get("immutable") is not True or candidate.get("production_eligible") is not False:
        raise RuntimeError("Daily cannot create a production-eligible candidate")
    components = spec["components"]
    if not components:
        raise RuntimeError("candidate policy has no components")
    owners = {component["source"]["repository"].split("/", 1)[0] for component in components}
    if len(owners) != 1:
        raise RuntimeError("one candidate policy must use one component repository owner")
    return spec, source_ref, owners.pop(), components


def declaration_mode(component_owner: str, components: list[dict]) -> None:
    repositories = []
    for component in components:
        owner, name = component["source"]["repository"].split("/", 1)
        if owner != component_owner:
            raise RuntimeError("component repository owner mismatch")
        repositories.append(name)
    output("component_owner", component_owner)
    output("component_repositories", "\n".join(sorted(set(repositories))))


def resolve_mode(spec: dict, source_ref: str, component_owner: str, components: list[dict]) -> None:
    dispatch = spec["uat_dispatch"]
    deploy = required("DEPLOY_AFTER_BUILD") == "true"
    target_ref = os.environ.get("SELECTED_TARGET_REF", "").strip()
    if deploy:
        if dispatch["status"] != "ready":
            raise RuntimeError("UAT dispatch owner is not ready in GitOps")
        if not target_ref:
            raise RuntimeError("target_ref is required for explicit UAT dispatch")
        if target_ref != dispatch["target_ref"]:
            raise RuntimeError("target_ref does not match the reviewed GitOps target")

    token = required("GITHUB_TOKEN_INPUT")
    repositories = sorted({component["source"]["repository"] for component in components})
    resolved_shas = {}
    for repository in repositories:
        commit = github(
            f"/repos/{repository}/commits/{urllib.parse.quote(source_ref, safe='')}", token
        )
        sha = commit["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError(f"invalid source SHA for {repository}")
        resolved_shas[repository] = sha

    requested = os.environ.get("REQUESTED_SNAPSHOT_TAG", "").strip()
    prefix = spec["candidate"]["id_prefix"]
    pattern = re.compile(rf"{re.escape(prefix)}-\d{{4}}\.\d{{2}}\.\d{{2}}-r[1-9]\d*")

    def occupied(candidate: str) -> list[str]:
        encoded = urllib.parse.quote(candidate, safe="")
        return [
            repository
            for repository in repositories
            if github(f"/repos/{repository}/git/ref/tags/{encoded}", token, True) is not None
        ]

    if requested:
        if not pattern.fullmatch(requested):
            raise RuntimeError("snapshot_tag must be an immutable UAT Daily candidate")
        existing = occupied(requested)
        if existing:
            raise RuntimeError(f"snapshot_tag is already occupied in: {', '.join(existing)}")
    else:
        date = time.strftime("%Y.%m.%d", time.gmtime())
        revision = 1
        while True:
            candidate = f"{prefix}-{date}-r{revision}"
            if not occupied(candidate):
                requested = candidate
                break
            revision += 1

    resolved_components = []
    for component in components:
        resolved = copy.deepcopy(component)
        repository = resolved["source"]["repository"]
        owner, name = repository.split("/", 1)
        resolved["resolved_source_sha"] = resolved_shas[repository]
        resolved["source_owner"] = owner
        resolved["source_repository_name"] = name
        resolved_components.append(resolved)

    owner_repository = dispatch.get("owner_repository", "")
    if owner_repository:
        uat_owner, uat_repository = owner_repository.split("/", 1)
    else:
        uat_owner, uat_repository = "", ""
    matrix = {
        "include": [
            {"name": component["name"], "component": component}
            for component in resolved_components
        ]
    }
    output("candidate_id", requested)
    output("component_matrix", matrix)
    output("gitops_sha", repository_sha(required("GITOPS_ROOT")))
    output("artifacts_sha", repository_sha(required("ARTIFACTS_ROOT")))
    output("iac_sha", repository_sha(required("IAC_ROOT")))
    output("playbooks_sha", repository_sha(required("PLAYBOOKS_ROOT")))
    output("uat_dispatch", dispatch)
    output("uat_owner", uat_owner)
    output("uat_repository", uat_repository)


def main() -> None:
    spec, source_ref, component_owner, components = load_contract()
    mode = required("RESOLVE_MODE")
    if mode == "declaration":
        declaration_mode(component_owner, components)
    elif mode == "resolve":
        resolve_mode(spec, source_ref, component_owner, components)
    else:
        raise RuntimeError("mode must be declaration or resolve")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - action must emit one sanitized failure
        print(f"::error::{error}")
        raise SystemExit(1) from error
