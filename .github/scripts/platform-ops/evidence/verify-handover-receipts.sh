#!/usr/bin/env bash
# Verify pre-collected, per-target handover receipts; never access target systems.
set -euo pipefail
[[ $# == 2 ]] || { echo 'usage: verify-handover-receipts.sh expected.json receipts.json' >&2; exit 2; }
expected=$1
receipts=$2
jq -e --slurpfile e "$expected" '
  ($e | length == 1) and ($e[0] as $expected |
    ($expected | type == "object") and
    ($expected.targets | type == "array" and length > 0 and all(.[]; type == "string" and length > 0) and (length == (unique | length))) and
    ($expected.environment | type == "string" and length > 0) and
    ($expected.gitops_sha | type == "string" and test("^[0-9a-f]{40}$")) and
    ($expected.playbooks_sha | type == "string" and test("^[0-9a-f]{40}$")) and
    ($expected.cmdb_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
    ($expected.run_id | type == "string" and test("^[1-9][0-9]*$")) and
    ($expected.run_attempt | type == "number" and . >= 1 and floor == .) and
    (type == "array") and
    (map(.target) | sort) == ($expected.targets | sort) and
    all(.[]; . as $r |
      $r.environment == $expected.environment and
      $r.gitops_sha == $expected.gitops_sha and
      $r.playbooks_sha == $expected.playbooks_sha and
      $r.cmdb_sha256 == $expected.cmdb_sha256 and
      $r.run_id == $expected.run_id and $r.run_attempt == $expected.run_attempt and
      $r.result == "success" and
      $r.handover.result == "FLUX_HANDOVER_VERIFIED" and
      $r.handover.node == $r.target and
      $r.handover.gitops_sha == $expected.gitops_sha and
      $r.handover.common.result == "COMMON_NODE_VERIFIED" and
      $r.identities.result == "K3S_IDENTITIES_VERIFIED" and
      $r.identities.rbac_revision == $expected.gitops_sha and
      $r.identities.principals == ["root", "operator", "auditor"]))
' "$receipts" >/dev/null
