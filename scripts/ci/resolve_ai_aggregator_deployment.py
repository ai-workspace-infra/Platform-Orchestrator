#!/usr/bin/env python3
"""Resolve an input-selected deployment from GitOps without environment mappings."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import yaml


PROVIDERS = {"aws", "gcp", "vps", "akamai-cloud"}
OPERATIONS = {"plan", "apply", "provision", "stage", "activate"}
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")
HOSTNAME = re.compile(r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*\Z")
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def resource_adapter(contract):
    """Identify the resource format, rather than choosing the deployment cloud."""
    renderer = contract.get("renderer", "")
    if renderer == "cmdb/inventory":
        return "existing"
    for directory, provider in (
        ("aws-cloud", "aws"), ("gcp-cloud", "gcp"),
        ("vultr-cloud", "vps"), ("vps-cloud", "vps"),
        ("akamai-cloud", "akamai-cloud"),
    ):
        if directory in Path(renderer).parts:
            return provider
    raise ValueError(f"unsupported resource renderer: {renderer}")


def resolve(
    root: Path,
    environment: str,
    profile: str,
    provider: str,
    operation: str,
    target_hostname: str = "",
    target_domain: str = "",
    ssh_user: str = "",
    resource_mode: str = "create",
):
    if not NAME.fullmatch(environment):
        raise ValueError("environment must be a lowercase name containing letters, digits or hyphens")
    if profile not in {"single-node", "distributed"}:
        raise ValueError(f"unsupported deployment profile: {profile}")
    if provider not in PROVIDERS or operation not in OPERATIONS:
        raise ValueError("unsupported provider or operation")
    if resource_mode not in {"create", "existing"}:
        raise ValueError("resource_mode must be create or existing")
    if provider != "akamai-cloud" and resource_mode != "create":
        raise ValueError("resource_mode existing is available only for Akamai Cloud")
    candidates = []
    directory = root / "topology" / environment / "selfhost"
    for path in sorted(directory.glob("ai-aggregator*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or data.get("kind") != "PersonalAIAggregator":
            continue
        metadata = data.get("metadata", {})
        if metadata.get("environment") != environment:
            raise ValueError(f"manifest environment does not match input {environment}: {path}")
        contract = data["spec"]["infrastructure"].get("resource_contract", {})
        if metadata.get("topology", "distributed") == profile and resource_adapter(contract) == provider:
            candidates.append((path, data))
    if len(candidates) != 1:
        raise ValueError(
            f"expected one GitOps declaration for environment={environment} "
            f"profile={profile} provider={provider}; found {len(candidates)} in {directory}"
        )
    path, data = candidates[0]
    selected = provider
    spec = data["spec"]
    infrastructure = spec["infrastructure"]
    enabled = spec.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"spec.enabled must be a YAML boolean: {path}")
    if operation in {"stage", "activate"} and not enabled:
        raise ValueError(f"{operation} requires spec.enabled: true in {path}; no resources will be created")
    entries = []
    contract = infrastructure.get("resource_contract", {})
    for raw in contract.get("manifests", []) if selected == "akamai-cloud" else []:
        entry = dict(raw)
        resource_path = Path(entry["path"])
        parts = resource_path.parts
        if (resource_path.is_absolute() or ".." in parts or len(parts) != 5
                or parts[0] != "resources" or parts[2:4] != (environment, "akamai")
                or resource_path.suffix != ".yaml"):
            raise ValueError(f"Akamai resource path must belong to the selected environment: {resource_path}")
        if not (root / resource_path).is_file():
            raise ValueError(f"Akamai resource declaration is missing: {resource_path}")
        account = entry.get("account", contract.get("account", ""))
        workspace = entry.get("workspace", "")
        if not NAME.fullmatch(account) or not NAME.fullmatch(workspace):
            raise ValueError("Akamai account and workspace must be lowercase names")
        entry.update(account=account)
        entries.append(entry)
    if selected == "akamai-cloud" and len(entries) != 1:
        raise ValueError("single-node Akamai deployment requires exactly one declared IaC resource manifest")
    domain = spec.get("entrypoint", {}).get("domain", "")
    nodes = spec.get("nodes", [])
    if selected == "akamai-cloud":
        if len(nodes) != 1 or profile != "single-node":
            raise ValueError("Akamai AI Aggregator handoff currently requires one single-node GitOps target")
        node = nodes[0]
        hostname = node.get("inventory_host", "")
        if not HOSTNAME.fullmatch(hostname) or not HOSTNAME.fullmatch(domain):
            raise ValueError("Akamai GitOps target must declare valid hostname and business domain")
        if not target_hostname or target_hostname != hostname:
            raise ValueError("target_hostname must exactly match the selected GitOps inventory_host")
        if not target_domain or target_domain != domain:
            raise ValueError("target_domain must exactly match the selected GitOps entrypoint domain")
        if entries[0].get("node") != node.get("id") or entries[0].get("role") != node.get("role"):
            raise ValueError("Akamai resource manifest must bind the selected GitOps node and role")
        if ssh_user and ssh_user != node.get("ssh_user"):
            raise ValueError("ssh_user must exactly match the selected GitOps node")
        if resource_mode == "existing" and infrastructure.get("lifecycle") != "persistent":
            raise ValueError("existing resource mode requires a persistent GitOps target")
        if operation in {"stage", "activate"}:
            artifacts = spec.get("artifacts", {})
            for artifact_name in ("new_api", "cliproxyapi"):
                artifact = artifacts.get(artifact_name, {})
                if not artifact.get("revision") or not SHA256.fullmatch(str(artifact.get("sha256", ""))):
                    raise ValueError(f"{operation} requires immutable version and SHA256 for {artifact_name}")
        if operation == "activate" and spec.get("apisix", {}).get("activation_validated") is not True:
            raise ValueError("activate requires reviewed APISIX and client-flow acceptance in GitOps")
    elif any((target_hostname, target_domain, ssh_user)):
        if not HOSTNAME.fullmatch(target_hostname) or not HOSTNAME.fullmatch(target_domain):
            raise ValueError("target hostname and domain must be DNS hostnames")
        matches = [node for node in nodes if node.get("inventory_host") == target_hostname]
        if len(matches) != 1 or domain != target_domain:
            raise ValueError("target hostname/domain must match the selected GitOps declaration")
        if ssh_user and ssh_user != matches[0].get("ssh_user"):
            raise ValueError("ssh_user must exactly match the selected GitOps node")
    target_manifest = contract.get("target_manifest", "")
    if selected == "akamai-cloud":
        target_path = Path(target_manifest)
        if (target_path.is_absolute() or ".." in target_path.parts or target_path.parts[:2] != ("iac", "targets")
                or target_path.suffix != ".yaml" or not (root / target_path).is_file()):
            raise ValueError("Akamai IaC target_manifest must be a reviewed GitOps iac/targets path")
    return {
        "provider": selected,
        "environment": environment,
        "profile": profile,
        "template_path": str(path),
        "manifest_path": str(root / ".runtime" / environment / "ai-aggregator.yaml"),
        "deployment_enabled": str(enabled).lower(),
        "lifecycle": infrastructure.get("lifecycle", ""),
        "domain_base": domain.partition(".")[2],
        "service_manifest": str(path.relative_to(root)),
        "iac_target_manifest": target_manifest,
        "account": contract.get("account", entries[0].get("account", "") if entries else ""),
        "target_hostname": target_hostname,
        "target_domain": target_domain,
        "ssh_user": ssh_user or (nodes[0].get("ssh_user", "") if selected == "akamai-cloud" else ""),
        "resource_mode": resource_mode,
    }


def materialize(outputs):
    """Build a runner-local declaration with event inputs as the selectors."""
    data = yaml.safe_load(Path(outputs["template_path"]).read_text())
    data["metadata"]["environment"] = outputs["environment"]
    infrastructure = data["spec"]["infrastructure"]
    infrastructure["provider"] = outputs["provider"]
    for node in data["spec"].get("nodes", []):
        node["provider"] = outputs["provider"]
    if data["spec"].get("testing_environment"):
        data["spec"]["testing_environment"]["provider"] = outputs["provider"]
    path = Path(outputs["manifest_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitops-root", type=Path, default=Path("gitops"))
    parser.add_argument("--environment", required=True)
    parser.add_argument("--profile", default="single-node")
    parser.add_argument("--provider", default="gcp")
    parser.add_argument("--operation", default="plan")
    parser.add_argument("--target-hostname", default="")
    parser.add_argument("--target-domain", default="")
    parser.add_argument("--ssh-user", default="")
    parser.add_argument("--resource-mode", default="create")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        outputs = resolve(
            args.gitops_root, args.environment, args.profile, args.provider,
            args.operation, args.target_hostname, args.target_domain, args.ssh_user, args.resource_mode,
        )
    except (ValueError, KeyError) as error:
        parser.exit(1, f"deployment resolution failed: {error}\n")
    materialize(outputs)
    args.output.write_text("".join(f"{key}={value}\n" for key, value in outputs.items()))
    print(f"provider={outputs['provider']} environment={outputs['environment']} manifest={outputs['manifest_path']}")


if __name__ == "__main__":
    main()
