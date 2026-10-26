#!/usr/bin/env python3
"""Select an already owner-verified runtime inventory; no cloud/host execution."""
import hashlib
import json
import os
from pathlib import Path

TARGET_ID = "dev-akamai-dev-k3s-v5"
HOST = "dev-k3s-v5"
STATE = "terraform/dev/svc.plus/akamai-cloud/manbuzhe2026/dev-k3s-v5/terraform.tfstate"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def select(summary, inventories, matrix):
    require(summary.get("result") == "applied_verified", "bootstrap requires applied_verified")
    context = summary["context"]
    require(context.get("environment") == "dev" and context.get("action") == "apply" and context.get("stages") == ["resources"], "wrong action/environment/stages")
    targets = context.get("targets", [])
    require(len(targets) == 1 and targets[0].get("id") == TARGET_ID, "not the unique Dev target")
    target = targets[0]
    for key, expected in {"environment": "dev", "project": "svc.plus", "provider": "akamai-cloud", "account": "manbuzhe2026", "namespace": HOST}.items():
        require(target.get(key) == expected, "target identity mismatch: " + key)
    require(target.get("stages", {}).get("resources", {}).get("state", {}).get("key") == STATE, "canonical Dev state mismatch")
    require(set(inventories) == {TARGET_ID}, "unexpected inventory target")
    cmdb = inventories[TARGET_ID]
    require(isinstance(cmdb, dict) and set(cmdb) == {HOST}, "runtime CMDB must contain exactly one Dev host")
    facts = cmdb[HOST]
    require(facts.get("name") == HOST and facts.get("label") == HOST, "runtime host identity mismatch")
    require(str(facts.get("instance_id", "")).isdecimal() and int(facts["instance_id"]) > 0 and facts.get("ip"), "missing runtime instance identity")
    require(summary.get("deploy_matrix") == matrix == [{"target_id": TARGET_ID, "host": HOST, **facts}], "deploy matrix does not match verified runtime inventory")
    receipts = summary.get("receipts", [])
    require(len(receipts) == 1 and receipts[0].get("target_id") == TARGET_ID and receipts[0].get("stage") == "resources", "missing resource receipt")
    raw = json.dumps(cmdb, sort_keys=True, indent=2) + "\n"
    require(hashlib.sha256(raw.encode()).hexdigest() == receipts[0].get("inventory_sha256"), "selected inventory digest differs from owner receipt")
    # This is a byte-equivalent selection of the owner's public target mapping,
    # never a fabricated inventory or a declaration-derived address.
    return raw, str(facts["instance_id"])


def main():
    require(os.environ["RECEIPT_ARTIFACT_ID"].isdigit() and os.environ["RECEIPT_ARTIFACT_ID"] == os.environ["INVENTORY_ARTIFACT_ID"], "expected one owner summary/inventory bundle")
    bundle = Path(os.environ["BUNDLE_DIR"])
    summary = json.loads((bundle / "summary.json").read_text())
    inventories = json.loads((bundle / "inventory.json").read_text())
    raw, instance_id = select(summary, inventories, json.loads(os.environ["DEPLOY_MATRIX"]))
    destination = Path(os.environ["DESTINATION"])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "cmdb.json").write_text(raw)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("instance_id=" + instance_id + "\n")
        output.write("cmdb_sha256=" + hashlib.sha256(raw.encode()).hexdigest() + "\n")


if __name__ == "__main__":
    main()
