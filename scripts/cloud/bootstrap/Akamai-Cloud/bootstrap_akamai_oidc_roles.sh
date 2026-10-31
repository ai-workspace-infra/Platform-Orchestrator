#!/usr/bin/env bash
set -Eeuo pipefail

# Render and publish the environment/account-specific Vault JWT roles and
# policies required by the Akamai Cloud/Linode GitHub Actions workflow.
# Account names are inputs; no account alias or secret is embedded here.
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VAULT_SCRIPT_DIR="$(cd -- "${SCRIPT_DIR}/../../../vault" && pwd -P)"
DECLARATION_READER="${VAULT_SCRIPT_DIR}/vault_declarations.py"
source "${VAULT_SCRIPT_DIR}/source_gitops.sh"

usage() {
  cat <<'EOF'
Usage:
  bootstrap_akamai_oidc_roles.sh [--check|--apply] [--env dev|uat|prod|all]

Required environment variables:
  VAULT_ADDR            Vault address, for example https://vault.svc.plus
  VAULT_TOKEN           Required for UAT/PROD/all; Dev may use an existing CLI helper session
  AKAMAI_ACCOUNT_DEV    Concrete Dev account, only for explicit --env dev
  AKAMAI_ACCOUNT_UAT    Concrete UAT Akamai account name or ID
  AKAMAI_ACCOUNT_PROD   Concrete PROD Akamai account name or ID

Optional environment variables:
  VAULT_JWT_AUTH_MOUNT  JWT auth mount (default: auth/jwt)
  ENV                   Default target environment (default: all)

Examples:
  export VAULT_ADDR=https://vault.svc.plus
  export VAULT_TOKEN='...'
  export AKAMAI_ACCOUNT_UAT='actual-uat-account'
  export AKAMAI_ACCOUNT_PROD='actual-prod-account'
  bash scripts/cloud/bootstrap/Akamai-Cloud/bootstrap_akamai_oidc_roles.sh --apply --env all

Use --check to verify the generated policy and role already exist.
Dev is opt-in (--env dev); all intentionally remains UAT + PROD.
Rendering a template does not authorize applying it to Vault.
EOF
}

mode=check
target_env="${ENV:-all}"
while (($# > 0)); do
  case "$1" in
    --check) mode=check ;;
    --apply) mode=apply ;;
    --env)
      (($# >= 2)) || { echo "--env requires dev, uat, prod, or all" >&2; exit 2; }
      target_env="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

target_env="${target_env,,}"
case "$target_env" in
  dev|uat|prod|all) ;;
  *) echo "invalid environment: ${target_env}" >&2; exit 2 ;;
esac

trap 'vault_gitops_source_cleanup' EXIT
vault_gitops_source_init

command -v vault >/dev/null 2>&1 || { echo "vault CLI is required" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
export VAULT_ADDR="${VAULT_ADDR:-https://vault.svc.plus}"
if [[ "$target_env" != dev ]]; then
  : "${VAULT_TOKEN:?VAULT_TOKEN must be provided through the environment}"
fi
VAULT_JWT_AUTH_MOUNT="${VAULT_JWT_AUTH_MOUNT:-auth/jwt}"
VAULT_JWT_AUTH_MOUNT="${VAULT_JWT_AUTH_MOUNT#/}"
VAULT_JWT_AUTH_MOUNT="${VAULT_JWT_AUTH_MOUNT%/}"

account_for_env() {
  local env_name="$1"
  local account=""
  case "$env_name" in
    dev) account="${AKAMAI_ACCOUNT_DEV:-}" ;;
    uat) account="${AKAMAI_ACCOUNT_UAT:-}" ;;
    prod) account="${AKAMAI_ACCOUNT_PROD:-}" ;;
  esac
  : "${account:?set AKAMAI_ACCOUNT_${env_name^^} to a concrete account name or ID}"
  [[ "$account" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    echo "invalid Akamai account: ${account}" >&2
    exit 2
  }
  case "$account" in
    primary|default|main)
      echo "account must be concrete, not alias: ${account}" >&2
      exit 2
      ;;
  esac
  printf '%s' "$account"
}

verify_dev_session() {
  local role_name="$1"
  local session_metadata capabilities path
  # The CLI resolves its own helper. Retain only nonsecret metadata, never id/token.
  if ! session_metadata="$(vault token lookup -format=json 2>/dev/null |
    jq -ce '{policies: .data.policies, ttl: .data.ttl}')"; then
    echo "::error::Dev requires a valid non-root Vault CLI session." >&2
    return 1
  fi
  if ! jq -e '
    (.policies | type == "array" and length > 0 and all(type == "string") and index("root") == null)
    and (.ttl | type == "number" and . > 0)
  ' <<<"$session_metadata" >/dev/null; then
    echo "::error::Dev refuses a root, invalid or expired Vault session." >&2
    return 1
  fi
  for path in "sys/policies/acl/${role_name}" "${VAULT_JWT_AUTH_MOUNT}/role/${role_name}"; do
    if ! capabilities="$(vault token capabilities -format=json "$path" 2>/dev/null)"; then
      echo "::error::Cannot verify Dev session capabilities for the exact managed path." >&2
      return 1
    fi
    if ! jq -e --arg mode "$mode" '
      type == "array" and index("root") == null and index("deny") == null
      and index("read") != null
      and ($mode == "check" or (index("create") != null and index("update") != null))
    ' <<<"$capabilities" >/dev/null; then
      echo "::error::Dev session lacks required capabilities on the exact managed path." >&2
      return 1
    fi
  done
}

publish_env() {
  local env_name="$1"
  local account="$2"
  local policy_name="github-actions-platform-ops-toolkit-${env_name}-akamai-oidc-bootstrap-${account}"
  local role_name="$policy_name"
  local policy_file role_file
  if [[ "$env_name" == dev ]]; then
    verify_dev_session "$role_name"
  elif [[ "$env_name" == prod ]]; then
    role_name="prod-akamai-iac"
  fi
  policy_file="${tmp_dir}/${env_name}-${account}.hcl"
  role_file="${tmp_dir}/${env_name}-${account}.json"

  python3 "${DECLARATION_READER}" template-policy --environment "${env_name}" --account "${account}" >"${policy_file}"
  python3 "${DECLARATION_READER}" template-role --environment "${env_name}" --account "${account}" --policy "${policy_name}" >"${role_file}"

  if [[ "$mode" == check ]]; then
    vault policy read "$policy_name" >/dev/null
    vault read "${VAULT_JWT_AUTH_MOUNT}/role/${role_name}" >/dev/null
    verify_role_claims "$env_name" "$account" "$role_name" "$policy_name"
    echo "present ${env_name}/${account}"
    return
  fi
  vault policy write "$policy_name" "$policy_file" >/dev/null
  jq -c 'del(.role_name, .description)' "$role_file" |
    vault write "${VAULT_JWT_AUTH_MOUNT}/role/${role_name}" - >/dev/null
  verify_role_claims "$env_name" "$account" "$role_name" "$policy_name"
  echo "written ${env_name}/${account}"
}

verify_role_claims() {
  local env_name="$1"
  local account="$2"
  local role_name="$3"
  local policy_name="$4"
  local expected_environment="$env_name"
  local role_json

  role_json="$(vault read -format=json "${VAULT_JWT_AUTH_MOUNT}/role/${role_name}")"
  if [[ "$env_name" == dev ]]; then
    if ! jq -e --arg policy "$role_name" '
      .data as $role
      | $role.bound_claims == {
          repository: "ai-workspace-infra/platform-ops-toolkit",
          ref: "refs/heads/main",
          environment: "dev",
          workflow_ref: "ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-host-lifecycle.yml@refs/heads/main",
          job_workflow_ref: "ai-workspace-infra/platform-ops-toolkit/.github/workflows/iac-pipeline-multi-cloud-stages.yaml@refs/heads/main"
        }
        and $role.bound_claims_type == "string"
        and $role.role_type == "jwt" and $role.user_claim == "sub"
        and $role.bound_audiences == ["vault"]
        and $role.token_policies == [$policy]
        and $role.token_no_default_policy == true
        and $role.token_type == "batch"
        and ([$role.token_ttl] | all(. == 1200 or . == "20m"))
        and ([$role.token_max_ttl] | all(. == 1200 or . == "20m"))
    ' <<<"$role_json" >/dev/null; then
      echo "::error::Dev Akamai role claims or token scope do not match the exact lifecycle caller/stage workflow contract." >&2
      return 1
    fi
    return
  fi
  if [[ "$env_name" == uat ]]; then
    if ! jq -e --arg repository "ai-workspace-infra/platform-ops-toolkit" \
      --arg role_policy "$role_name" '
        .data as $role
        | $role.bound_claims.repository == $repository
          and ($role.bound_claims.ref | if type == "array" then index("refs/heads/main") != null else . == "refs/heads/main" end)
          and $role.bound_claims.environment == "uat"
          and $role.token_policies == [$role_policy]
          and $role.token_no_default_policy == true
          and $role.token_type == "batch"
          and ($role.token_ttl == 1200 or $role.token_ttl == "20m")
          and ($role.token_max_ttl == 1200 or $role.token_max_ttl == "20m")
      ' <<<"$role_json" >/dev/null; then
      echo "::error::UAT Akamai role claims or token scope do not match the existing UAT contract." >&2
      return 1
    fi
    return
  fi
  if ! jq -e \
    --arg repository "ai-workspace-infra/Platform-Orchestrator" \
    --arg stage_workflow "ai-workspace-infra/Platform-Orchestrator/.github/workflows/iac-pipeline-multi-cloud-stages.yaml@refs/heads/main" \
    --arg aggregator_workflow "ai-workspace-infra/Platform-Orchestrator/.github/workflows/ai-aggregator-v1.yml@refs/heads/main" \
    --arg expected_environment "$expected_environment" \
    --arg policy "$policy_name" '
      .data as $role
      | $role.bound_claims as $claims
      | $claims.repository == $repository
        and ($claims.job_workflow_ref == [$stage_workflow, $aggregator_workflow]
          or $claims.job_workflow_ref == [$aggregator_workflow, $stage_workflow])
        and $claims.ref == "refs/heads/main"
        and $claims.environment == $expected_environment
        and $role.bound_claims_type == "glob"
        and $role.role_type == "jwt" and $role.user_claim == "sub"
        and $role.bound_audiences == ["vault"]
        and $role.token_policies == [$policy]
        and $role.token_no_default_policy == true
        and $role.token_type == "batch"
        and ($role.token_ttl == 1200 or $role.token_ttl == "20m")
        and ($role.token_max_ttl == 1200 or $role.token_max_ttl == "20m")
    ' <<<"$role_json" >/dev/null; then
    echo "::error::Vault role ${role_name} was written/read, but its repository/ref/environment/job_workflow_ref claims are not the Akamai Cloud contract for ${env_name}/${account}." >&2
    echo "::error::Required caller is iac-pipeline-multi-cloud-stages.yaml on main, with the exact ${expected_environment} GitHub Environment and account-scoped policy ${policy_name}." >&2
    return 1
  fi
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"; vault_gitops_source_cleanup' EXIT

environments=(uat prod)
if [[ "$target_env" != all ]]; then
  environments=("$target_env")
fi

for env_name in "${environments[@]}"; do
  publish_env "$env_name" "$(account_for_env "$env_name")"
done

echo "Akamai Cloud Vault OIDC role/policy ${mode} completed."
