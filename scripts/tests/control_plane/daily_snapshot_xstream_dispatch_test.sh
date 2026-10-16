#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
config="${repo_root}/.github/daily-snapshot-builds.json"
tagger="${repo_root}/docs/tasks/tag-ai-workspace-mains.sh"
waiter="${repo_root}/.github/scripts/snapshots/wait-daily-snapshot-builds.sh"

for repo in ai-workspace-xstream/xray-exporter ai-workspace-xstream/xconnect-edge-agent; do
  jq -e --arg repo "${repo}" '
    .repositories[] | select(.repository == $repo and .trigger == "workflow_dispatch")
  ' "${config}" >/dev/null
done

grep -Fq 'ai-workspace-xstream/xray-exporter) printf' "${tagger}"
grep -Fq 'ai-workspace-xstream/xconnect-edge-agent) printf' "${tagger}"
grep -Fq 'release_tag=${tag}' "${tagger}"
grep -Fq 'source_ref=${tag}' "${tagger}"
grep -Eq 'ai-workspace-xstream/xray-exporter\|ai-workspace-xstream/xconnect-edge-agent\) printf.*workflow_dispatch' "${waiter}" || {
  echo "xstream snapshot builds must be matched as workflow_dispatch runs" >&2
  exit 1
}

bash -n "${tagger}" "${waiter}"
echo "daily snapshot xstream dispatch contract passed"
