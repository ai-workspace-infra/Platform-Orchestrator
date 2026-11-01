#!/usr/bin/env python3
"""Select a receipt-bound single-host runtime inventory; no cloud/host execution."""
import hashlib
import json
import os
from pathlib import Path

def require(condition, message):
    if not condition:
        raise ValueError(message)


def select(summary, inventories, matrix):
    require(summary.get("result") == "applied_verified", "runtime handoff requires applied_verified")
    context = summary["context"]
    require(context.get("action") == "apply" and context.get("stages") == ["resources"], "runtime handoff requires a resources-only apply")
    targets = context.get("targets", [])
    require(len(targets) == 1 and isinstance(targets[0].get("id"), str), "runtime handoff requires exactly one declared target")
    target = targets[0]
    target_id = target["id"]
    require(target.get("environment") == context.get("environment"), "target/environment identity mismatch")
    require(all(isinstance(target.get(key), str) and target[key] for key in ("project", "provider", "account", "namespace")), "target identity is incomplete")
    state_key = target.get("stages", {}).get("resources", {}).get("state", {}).get("key")
    require(isinstance(state_key, str) and state_key, "target resources state identity is missing")
    require(set(inventories) == {target_id}, "unexpected inventory target")
    cmdb = inventories[target_id]
    require(isinstance(cmdb, dict) and len(cmdb) == 1, "runtime CMDB must contain exactly one host")
    host, facts = next(iter(cmdb.items()))
    require(isinstance(host, str) and isinstance(facts, dict), "runtime host facts are malformed")
    require(facts.get("name") == host and facts.get("label") == host, "runtime host identity mismatch")
    require(str(facts.get("instance_id", "")).isdecimal() and int(facts["instance_id"]) > 0 and facts.get("ip"), "missing runtime instance identity")
    require(summary.get("deploy_matrix") == matrix == [{"target_id": target_id, "host": host, **facts}], "deploy matrix does not match verified runtime inventory")
    receipts = summary.get("receipts", [])
    require(len(receipts) == 1 and receipts[0].get("target_id") == target_id and receipts[0].get("stage") == "resources", "missing resource receipt")
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
