#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
verify="$root/.github/scripts/platform-ops/evidence/verify-handover-receipts.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
jq -n '{targets:["node-a","node-b"],environment:"prod",gitops_sha:("a"*40),playbooks_sha:("b"*40),cmdb_sha256:("c"*64),run_id:"123",run_attempt:1}' > "$tmp/expected"
jq '[.targets[] as $target | {target:$target,environment,gitops_sha,playbooks_sha,cmdb_sha256,run_id,run_attempt,result:"success",handover:{result:"FLUX_HANDOVER_VERIFIED",node:$target,gitops_sha,common:{result:"COMMON_NODE_VERIFIED"}},identities:{result:"K3S_IDENTITIES_VERIFIED",rbac_revision:.gitops_sha,principals:["root","operator","auditor"]}}]' "$tmp/expected" > "$tmp/receipts"
"$verify" "$tmp/expected" "$tmp/receipts"
for mutation in '.[0:1]' '.[1].result="failed"' '.[1].gitops_sha="wrong"' '.[1].target="node-a"' '.[0].identities.principals=["root"]'; do
  jq "$mutation" "$tmp/receipts" > "$tmp/bad"
  if "$verify" "$tmp/expected" "$tmp/bad"; then echo "unexpected acceptance: $mutation" >&2; exit 1; fi
done
jq '.targets=[]' "$tmp/expected" > "$tmp/empty"
if "$verify" "$tmp/empty" "$tmp/receipts"; then echo 'unexpected acceptance: empty targets' >&2; exit 1; fi
mkdir -p "$tmp/artifacts/k3s-handover-node-a-1" "$tmp/artifacts/k3s-handover-node-b-1"
jq '.[0]' "$tmp/receipts" > "$tmp/artifacts/k3s-handover-node-a-1/receipt.json"
jq '.[1]' "$tmp/receipts" > "$tmp/artifacts/k3s-handover-node-b-1/receipt.json"
export HANDOVER_DIRECTORY="$tmp/artifacts" RUNNER_TEMP="$tmp" EXPECTED_TARGETS='["node-a","node-b"]' DEPLOYMENT_ENVIRONMENT=prod
export GITOPS_SHA="$(jq -r .gitops_sha "$tmp/expected")" PLAYBOOKS_SHA="$(jq -r .playbooks_sha "$tmp/expected")" CMDB_SHA256="$(jq -r .cmdb_sha256 "$tmp/expected")" GITHUB_RUN_ID=123 GITHUB_RUN_ATTEMPT=1
bash "$root/.github/scripts/platform-ops/evidence/aggregate-k3s-handover.sh"
rm "$tmp/artifacts/k3s-handover-node-b-1/receipt.json"
if bash "$root/.github/scripts/platform-ops/evidence/aggregate-k3s-handover.sh"; then echo 'missing target accepted' >&2; exit 1; fi
