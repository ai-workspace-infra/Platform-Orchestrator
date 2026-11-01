#!/usr/bin/env python3
"""Validate an existing AI Aggregator target and render its run-local CMDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import yaml


USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}\$?\Z")


def render(manifest_path: Path, lightsail_facts_path: Path, ip: str, hostname: str, domain: str, ssh_user: str) -> dict:
    manifest = yaml.safe_load(manifest_path.read_text())
    if manifest.get("kind") != "PersonalAIAggregator" or manifest.get("metadata", {}).get("environment") != "prod":
        raise ValueError("existing-target CMDB requires a production PersonalAIAggregator declaration")
    if not USER_RE.fullmatch(ssh_user):
        raise ValueError("ssh_user contains unsupported characters")
    if manifest.get("spec", {}).get("entrypoint", {}).get("domain") != domain:
        raise ValueError("target_domain does not match the GitOps entrypoint domain")
    nodes = [node for node in manifest["spec"].get("nodes", []) if node.get("inventory_host") == hostname]
    if len(nodes) != 1:
        raise ValueError("target_hostname must match exactly one GitOps inventory_host")
    node = nodes[0]
    if node.get("ssh_user") != ssh_user:
        raise ValueError("SSH user does not match the selected GitOps node")

    facts = json.loads(lightsail_facts_path.read_text())
    instances = [instance for instance in facts.get("instances", []) if instance.get("publicIpAddress") == ip]
    if len(instances) != 1:
        raise ValueError(f"expected exactly one Lightsail instance for target IP; found {len(instances)}")
    instance = instances[0]
    region = instance.get("location", {}).get("regionName", "")
    if instance.get("state", {}).get("name") != "running" or region != "ap-northeast-1":
        raise ValueError("Lightsail instance state or expected Tokyo region does not match")
    if not instance.get("arn") or not instance.get("name"):
        raise ValueError("Lightsail instance identity is missing")

    roles = set(node.get("roles", [node.get("role", "")]))
    groups = [f"ai_aggregator_{role}" for role in ("gateway", "cpa") if role in roles]
    if not groups:
        raise ValueError("selected GitOps node must declare gateway or cpa role")
    record = {
        "ip": ip,
        "private_ip": instance.get("PrivateIpAddress"),
        "resource_id": instance["arn"],
        "ansible_user": ssh_user,
        "groups": groups,
        "host_vars": {"service_domains": [domain]},
    }
    return {
        "schema_version": "cmdb.v1",
        "environment": "prod",
        "cloud_provider": "aws",
        "region": region,
        "source_resources": ["lightsail:GetInstances"],
        "hosts": {hostname: record},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--lightsail-facts", type=Path, required=True)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--ssh-user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        cmdb = render(args.manifest, args.lightsail_facts, args.ip, args.hostname, args.domain, args.ssh_user)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"existing-target CMDB validation failed: {error}\n")
    args.output.write_text(json.dumps(cmdb, separators=(",", ":")))


if __name__ == "__main__":
    main()
