#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${CLOUDFLARE_BOUNDARY_CONFIG:?CLOUDFLARE_BOUNDARY_CONFIG is required}"
PORTAL_DIR="${PORTAL_DIR:?PORTAL_DIR is required}"
portal_env="${PORTAL_ENV:-uat}"
portal_config="${PORTAL_DIR}/src/config/runtime-service-config.${portal_env}.yaml"

test -f "${portal_config}" || { echo "Portal ${portal_env} runtime config not found: ${portal_config}" >&2; exit 1; }

# SIT/UAT Portal configs are expected to address the mode-qualified serverless
# hosts directly. Production Portal config intentionally uses customer-facing
# canonical domains; those aliases are governed by the separate DNS cutover
# procedure and must not be compared to internal serverless hostnames here.
if [[ "${portal_env}" == "prod" ]]; then
  echo "Portal prod uses canonical public domains; skipping internal serverless host parity check"
  exit 0
fi

console_host="$(jq -er '.spec.serverless.console_host' "${CONFIG_FILE}")"
accounts_host="$(jq -er '.spec.serverless.accounts_host' "${CONFIG_FILE}")"
# YAML may include a separate selfhost mapping with the same key names.
# Read only top-level strings; aliases and arbitrary YAML objects are disabled.
portal_origins="$(ruby -ryaml -rjson -e '
  document = YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], permitted_symbols: [], aliases: false)
  abort("Portal runtime config must be a YAML mapping") unless document.is_a?(Hash)
  keys = %w[dashboardUrl authUrl apiBaseUrl]
  abort("Portal runtime origins must be non-empty top-level strings") unless keys.all? { |key| document[key].is_a?(String) && !document[key].empty? }
  puts JSON.generate(document.slice(*keys))
' "${portal_config}")"
portal_dashboard="$(jq -er '.dashboardUrl' <<<"${portal_origins}")"
portal_auth="$(jq -er '.authUrl' <<<"${portal_origins}")"
portal_api="$(jq -er '.apiBaseUrl' <<<"${portal_origins}")"

matches_origin() {
  local actual="$1"
  local suffix="$2"
  shift 2
  local host
  for host in "$@"; do
    [[ "${actual}" == "https://${host}${suffix}" ]] && return 0
  done
  return 1
}

console_hosts=("${console_host}")
while IFS= read -r alias; do
  [[ -n "${alias}" ]] && console_hosts+=("${alias}")
done < <(jq -r '.spec.serverless.console_aliases[]? // empty' "${CONFIG_FILE}")

accounts_hosts=("${accounts_host}")
while IFS= read -r alias; do
  [[ -n "${alias}" ]] && accounts_hosts+=("${alias}")
done < <(jq -r '.spec.serverless.accounts_aliases[]? // empty' "${CONFIG_FILE}")

matches_origin "${portal_dashboard}" "" "${console_hosts[@]}" || {
  echo "Portal dashboardUrl (${portal_dashboard}) differs from GitOps Console host or aliases" >&2
  exit 1
}
matches_origin "${portal_auth}" "" "${accounts_hosts[@]}" || {
  echo "Portal authUrl (${portal_auth}) differs from GitOps Accounts host or aliases" >&2
  exit 1
}
matches_origin "${portal_api}" "/api" "${accounts_hosts[@]}" || {
  echo "Portal apiBaseUrl (${portal_api}) differs from GitOps Accounts host or aliases" >&2
  exit 1
}

echo "Portal ${portal_env} domains match GitOps: Console=${portal_dashboard}, Accounts=${portal_auth}"
