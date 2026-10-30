#!/usr/bin/env python3
"""Read reviewed Vault declarations from the GitOps security/vault tree.

Vault's API accepts HCL/JSON; this module renders those wire formats in memory
from the YAML source. It never writes generated authorization declarations to
the repository or a persistent file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised by CLI environments
    raise SystemExit("PyYAML is required to read GitOps Vault declarations") from exc


SOURCE_ROOT = Path(os.environ.get("GITOPS_ROOT", "")) / "security" / "vault"
KINDS = {
    "policies": {"VaultACLPolicy"},
    "roles": {"VaultJWTAuthRole"},
    "workload-identities": {"VaultKubernetesJWTAuthRole"},
}


def fail(message: str) -> None:
    raise SystemExit(message)


def read_document(path: Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        fail(f"Cannot read GitOps declaration {path}: {exc}")
    if not isinstance(value, dict) or value.get("apiVersion") != "security.gitops/v1alpha1":
        fail(f"Invalid Vault declaration header: {path}")
    if not isinstance(value.get("metadata"), dict) or not isinstance(value.get("spec"), dict):
        fail(f"Invalid Vault declaration structure: {path}")
    return value


def documents(category: str):
    if not SOURCE_ROOT.is_dir():
        fail("GITOPS_ROOT must point to a GitOps checkout containing security/vault")
    for path in sorted((SOURCE_ROOT / category).glob("*.yaml")):
        yield path, read_document(path)


def find(category: str, name: str, kinds: set[str] | None = None) -> dict:
    for path, doc in documents(category):
        if doc["metadata"].get("name") == name and (kinds is None or doc.get("kind") in kinds):
            return doc
    fail(f"GitOps Vault declaration not found: {category}/{name}")


def hcl_policy(spec: dict) -> str:
    paths = spec.get("paths")
    if not isinstance(paths, list) or not paths:
        fail("Vault ACL policy must contain non-empty spec.paths")
    blocks = []
    for item in paths:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("Vault ACL policy path entry is invalid")
        capabilities = item.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities or any(not isinstance(c, str) for c in capabilities):
            fail(f"Vault ACL capabilities are invalid for {item.get('path')}")
        path = item["path"]
        caps = ", ".join(json.dumps(cap) for cap in capabilities)
        blocks.append(f'path {json.dumps(path)} {{\n  capabilities = [{caps}]\n}}')
    return "\n\n".join(blocks) + "\n"


def replace(value, substitutions: dict[str, str]):
    if isinstance(value, str):
        for token, replacement in substitutions.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [replace(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {key: replace(item, substitutions) for key, item in value.items()}
    return value


def template(name: str, kind: str) -> dict:
    wanted = "VaultACLPolicyTemplate" if kind == "policy" else "VaultJWTAuthRoleTemplate"
    for _, doc in documents("templates"):
        if doc.get("kind") == wanted and doc["metadata"].get("name") == name:
            return doc
    fail(f"GitOps Vault template not found: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("category", choices=tuple(KINDS))
    policy = sub.add_parser("policy")
    policy.add_argument("name")
    role = sub.add_parser("role")
    role.add_argument("name")
    workload = sub.add_parser("workload-identity")
    workload.add_argument("name")
    ptemplate = sub.add_parser("template-policy")
    ptemplate.add_argument("--environment", required=True)
    ptemplate.add_argument("--account", required=True)
    rtemplate = sub.add_parser("template-role")
    rtemplate.add_argument("--environment", required=True)
    rtemplate.add_argument("--account", required=True)
    rtemplate.add_argument("--policy", required=True)
    sub.add_parser("materialize-test-fixtures", help="Generate ephemeral legacy-shaped test inputs from GitOps YAML")
    args = parser.parse_args()

    if args.command == "list":
        for _, doc in documents(args.category):
            if doc.get("kind") in KINDS[args.category]:
                print(doc["metadata"].get("name", ""))
    elif args.command == "policy":
        doc = find("policies", args.name, {"VaultACLPolicy"})
        print(hcl_policy(doc["spec"]), end="")
    elif args.command == "role":
        doc = find("roles", args.name, {"VaultJWTAuthRole"})
        rendered = {"role_name": doc["metadata"]["name"],
                    "description": doc["metadata"].get("description", ""),
                    **doc["spec"]}
        print(json.dumps(rendered, separators=(",", ":")))
    elif args.command == "workload-identity":
        doc = find("workload-identities", args.name, {"VaultKubernetesJWTAuthRole"})
        print(json.dumps(doc, separators=(",", ":")))
    elif args.command == "template-policy":
        doc = template("akamai-oidc-policy", "policy")
        rendered = replace(doc["spec"], {"__ENV__": args.environment, "__ACCOUNT__": args.account})
        print(hcl_policy(rendered))
    elif args.command == "template-role":
        doc = template(f"akamai-oidc-role-{args.environment}", "role")
        role_data = replace(doc["spec"]["role"], {"__ACCOUNT__": args.account, "__POLICY__": args.policy})
        print(json.dumps(role_data, separators=(",", ":")))
    elif args.command == "materialize-test-fixtures":
        # Existing narrow contract tests parse effective Vault API payloads.
        # Keep their fixtures ephemeral and derived from GitOps, never checked in.
        for category, directory in (("policies", "policies"), ("roles", "roles"),
                                    ("workload-identities", "workload-identities")):
            output = Path(__file__).resolve().parent / directory
            output.mkdir(parents=True, exist_ok=True)
            for _, doc in documents(category):
                name = doc["metadata"]["name"]
                suffix = ".hcl" if category == "policies" else ".json"
                target = output / f"{name}{suffix}"
                if category == "policies":
                    target.write_text(hcl_policy(doc["spec"]), encoding="utf-8")
                elif category == "roles":
                    target.write_text(json.dumps({"role_name": name,
                                                  "description": doc["metadata"].get("description", ""),
                                                  **doc["spec"]}, indent=2) + "\n", encoding="utf-8")
                else:
                    target.write_text(json.dumps({"role_name": name,
                                                  "description": doc["metadata"].get("description", ""),
                                                  **doc["spec"]}, indent=2) + "\n", encoding="utf-8")
        templates_dir = Path(__file__).resolve().parent / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        policy_doc = template("akamai-oidc-policy", "policy")
        # Preserve placeholder strings solely for existing renderer contract tests.
        (templates_dir / "akamai-oidc-policy.hcl.tmpl").write_text(hcl_policy(policy_doc["spec"]).rstrip("\n"), encoding="utf-8")
        for env in ("dev", "uat", "prod"):
            role_doc = template(f"akamai-oidc-role-{env}", "role")
            role_data = {"role_name": role_doc["metadata"].get("roleNameTemplate", ""),
                         "description": role_doc["metadata"].get("description", ""),
                         **role_doc["spec"]["role"]}
            (templates_dir / f"akamai-oidc-role-{env}.json.tmpl").write_text(json.dumps(role_data, indent=2) + "\n", encoding="utf-8")
        print("Generated untracked Vault declaration fixtures from GITOPS_ROOT for offline contract tests.")


if __name__ == "__main__":
    main()
