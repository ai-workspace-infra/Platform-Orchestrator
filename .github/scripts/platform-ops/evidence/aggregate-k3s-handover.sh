#!/usr/bin/env bash
set -euo pipefail
: "${HANDOVER_DIRECTORY:?}" "${EXPECTED_TARGETS:?}" "${DEPLOYMENT_ENVIRONMENT:?}" "${GITOPS_SHA:?}" "${PLAYBOOKS_SHA:?}" "${CMDB_SHA256:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" "${RUNNER_TEMP:?}"
expected="$RUNNER_TEMP/handover-expected.json"
receipts="$RUNNER_TEMP/handover-receipts.json"
jq -n --argjson targets "$EXPECTED_TARGETS" --arg environment "$DEPLOYMENT_ENVIRONMENT" --arg gitops_sha "$GITOPS_SHA" --arg playbooks_sha "$PLAYBOOKS_SHA" --arg cmdb_sha256 "$CMDB_SHA256" --arg run_id "$GITHUB_RUN_ID" --argjson run_attempt "$GITHUB_RUN_ATTEMPT" '{targets:$targets,environment:$environment,gitops_sha:$gitops_sha,playbooks_sha:$playbooks_sha,cmdb_sha256:$cmdb_sha256,run_id:$run_id,run_attempt:$run_attempt}' > "$expected"
shopt -s nullglob
files=("$HANDOVER_DIRECTORY"/k3s-handover-*/*.json)
((${#files[@]} > 0)) || { echo 'Required K3s handover receipts are missing' >&2; exit 1; }
jq -s '.' "${files[@]}" > "$receipts"
"$(dirname "$0")/verify-handover-receipts.sh" "$expected" "$receipts"
