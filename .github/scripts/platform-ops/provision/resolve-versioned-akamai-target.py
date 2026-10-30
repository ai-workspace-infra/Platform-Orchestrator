#!/usr/bin/env python3
"""Resolve a generation profile from the reviewed GitOps target and resource."""
import argparse
import json
from pathlib import Path
import re
import yaml


def resolve(root, profile, account):
    if not re.fullmatch(r"prod-v[0-9]+", profile):
        raise ValueError("invalid generation profile")
    root = Path(root).resolve(strict=True)
    matches = []
    for path in sorted((root / "iac/targets").glob("*.yaml")):
        document = yaml.safe_load(path.read_text()) or {}
        for target in document.get("targets", []):
            if (target.get("environment"), target.get("provider"), target.get("account")) != ("prod", "akamai-cloud", account):
                continue
            spec = target.get("stages", {}).get("resources", {})
            manifest = (root / spec.get("manifest", "")).resolve()
            if root not in manifest.parents or not manifest.is_file():
                continue
            resource = yaml.safe_load(manifest.read_text())
            hosts = resource.get("hosts", [])
            if len(hosts) != 1 or hosts[0].get("host_vars", {}).get("target_generation") != profile:
                continue
            declaration = resource["global"]
            for key in ("environment", "provider", "account", "project", "workspace"):
                if declaration.get(key) != target.get(key):
                    raise ValueError("target/resource identity mismatch")
            # A generation may be either an existing-state rollout or a fresh,
            # protected create-only bootstrap.  Both are valid when declared by
            # GitOps; the IaC stage is responsible for enforcing the matching
            # state/create contract.
            if spec.get("mode") != "terraform":
                raise ValueError("generation deployment requires a Terraform resource stage")
            if not (spec.get("requires_existing_state") is True or spec.get("create_only") is True):
                raise ValueError("generation deployment must declare existing-state or create-only semantics")
            state_key = spec["state"]["key"]
            expected = f"terraform/prod/{target['project']}/akamai-cloud/{account}/{target['workspace']}/terraform.tfstate"
            if state_key != expected:
                raise ValueError("state does not match the declared target identity")
            matches.append(dict(project=target["project"], workspace=target["workspace"],
                state_key=state_key, resource_manifest=str(manifest),
                target_manifest=str(path.relative_to(root)), region=declaration["region"]))
    if len(matches) != 1:
        raise ValueError("require exactly one reviewed Akamai generation target")
    return matches[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gitops-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    print(json.dumps(resolve(args.gitops_root, args.profile, args.account)))
