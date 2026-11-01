#!/usr/bin/env bash
set -euo pipefail
umask 077

# Reconcile shared GCP bootstrap/runtime and Vault node service JWT roles for
# both the source open-platform-prod project and target open-platform-shared.
# Default is read-only --check; use --apply to write the declared roles/policies.

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${script_dir}/source_gitops.sh"
declaration_reader="${script_dir}/vault_declarations.py"
vault_addr="${VAULT_ADDR:-https://vault.svc.plus}"
mode=check
runtime_mode=disabled
runtime_environment=uat

while (($#)); do
  case "$1" in
    --check) mode=check ;;
    --apply) mode=apply ;;
    --write-runtime) runtime_mode=enabled ;;
    --runtime-environment) runtime_environment="${2:?missing --runtime-environment value}"; shift ;;
    --runtime-environment=*) runtime_environment="${1#*=}" ;;
    -h|--help)
      printf 'Usage: %s [--check|--apply]\n' "$0"
  printf 'Targets reviewed shared GCP/Vault roles and optionally kv/<env>/serverless/gcp runtime identity.\n'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

trap 'vault_gitops_source_cleanup' EXIT
vault_gitops_source_init
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"; vault_gitops_source_cleanup' EXIT
role_dir="${tmp_dir}/roles"
policy_dir="${tmp_dir}/policies"
mkdir -p "${role_dir}" "${policy_dir}"

export VAULT_ADDR="${vault_addr}"
for command_name in vault jq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "${command_name} is required" >&2
    exit 1
  }
done
if [[ -z "${VAULT_TOKEN:-}" ]] && ! vault token lookup >/dev/null 2>&1; then
  echo "Vault authentication is required; use an authorized admin CLI session or VAULT_TOKEN." >&2
  exit 1
fi

names=(
  github-actions-platform-ops-toolkit-shared-gcp-bootstrap-open-platform-prod
  github-actions-platform-ops-toolkit-shared-gcp-oidc-open-platform-prod
  github-actions-platform-ops-toolkit-shared-gcp-bootstrap-open-platform-shared
  github-actions-platform-ops-toolkit-shared-gcp-oidc-open-platform-shared
  github-actions-platform-ops-toolkit-shared-gcp-service-open-platform-shared
  github-actions-platform-ops-toolkit-shared-vault-node-oidc-open-platform-prod
  github-actions-platform-ops-toolkit-shared-vault-node-oidc-open-platform-shared
  github-actions-platform-ops-toolkit-shared-vault-monitoring
  github-actions-platform-ops-toolkit-shared-vault-xconnect
  github-actions-platform-ops-toolkit-shared-vault-legacy-ssh
  github-actions-platform-ops-toolkit-shared-vault-snapshot
  github-actions-platform-ops-toolkit-shared-vault-raft-operator
  github-actions-platform-ops-toolkit-shared-xconnect-network
)

for name in "${names[@]}"; do
  role_file="${role_dir}/${name}.json"
  policy_file="${policy_dir}/${name}.hcl"
  python3 "${declaration_reader}" role "${name}" >"${role_file}"
  python3 "${declaration_reader}" policy "${name}" >"${policy_file}"
  test -f "${role_file}" && test -f "${policy_file}" || {
    echo "Missing shared Vault declaration for ${name}" >&2
    exit 1
  }
  if [[ "${name}" == *-bootstrap-* ]]; then
    workflow_claim=workflow_ref
    workflow_value="ai-workspace-infra/platform-ops-toolkit/.github/workflows/gcp-oidc-bootstrap.yml@refs/heads/main"
  elif [[ "${name}" == *-gcp-oidc-* ]]; then
    workflow_claim=job_workflow_ref
    workflow_value="ai-workspace-infra/platform-ops-toolkit/.github/workflows/gcp-iac-pipeline.yml@*"
  elif [[ "${name}" == *-gcp-service-* ]]; then
    workflow_claim=job_workflow_ref
    workflow_value="ai-workspace-infra/platform-ops-toolkit/.github/workflows/observability-server.yml@refs/heads/main"
  elif [[ "${name}" == *-shared-xconnect-network ]]; then
    workflow_claim=job_workflow_ref
    workflow_value="ai-workspace-infra/platform-ops-toolkit/.github/workflows/xconnect-zero-cloud.yaml@refs/heads/main"
  else
    workflow_claim=workflow_ref
    workflow_value="ai-workspace-infra/platform-ops-toolkit/.github/workflows/vault-server.yml@refs/heads/main"
  fi
  jq -e --arg name "${name}" --arg workflow_claim "${workflow_claim}" --arg workflow_value "${workflow_value}" '
    .role_name == $name and
    .role_type == "jwt" and
    .user_claim == "sub" and
    .token_no_default_policy == true and
    .token_type == "batch" and
    (.bound_claims.repository == "ai-workspace-infra/platform-ops-toolkit") and
    (if ($name | contains("shared-vault-")) then
      .bound_claims.repository_id == "1284966060" and
      .bound_claims.repository_owner_id == "292703558"
     else true end) and
    (.bound_claims.environment == "prod") and
    (.bound_claims.ref == "refs/heads/main") and
    (.bound_claims[$workflow_claim] ==
      (if ($name | contains("-bootstrap-")) then
         [$workflow_value, "ai-workspace-infra/platform-ops-toolkit/.github/workflows/iac-orchestrator.yml@refs/heads/main"]
       elif ($name | contains("-gcp-oidc-")) then
         [$workflow_value, "ai-workspace-infra/platform-ops-toolkit/.github/workflows/iac-pipeline-multi-cloud-stages.yaml@refs/heads/main"]
       else $workflow_value end)) and
    (.token_policies | length == 1 and .[0] == $name)
  ' "${role_file}" >/dev/null || {
    echo "Invalid or unexpectedly broad shared role declaration: ${role_file}" >&2
    exit 1
  }

  if [[ "${mode}" == apply ]]; then
    echo "Writing shared GCP policy ${name}..."
    vault policy write "${name}" "${policy_file}" >/dev/null
    echo "Writing shared GCP JWT role ${name}..."
    jq -c 'del(.role_name, .description)' "${role_file}" |
      vault write "auth/jwt/role/${name}" - >/dev/null
  else
    vault policy read "${name}" >/dev/null
    vault read -format=json "auth/jwt/role/${name}" |
      jq -e --slurpfile expected "${role_file}" \
        '.data.bound_claims == $expected[0].bound_claims and .data.token_policies == $expected[0].token_policies' >/dev/null || {
          echo "${name}: Vault JWT role does not match the declared workflow ref; run --apply" >&2
          exit 1
        }
    echo "${name}: present and workflow claim matches"
  fi
done

if [[ "${runtime_mode}" == enabled ]]; then
  [[ "${runtime_environment}" =~ ^(uat|prod|shared)$ ]] || {
    echo "--runtime-environment must be uat, prod, or shared" >&2
    exit 2
  }
  if [[ -z "${GCP_WORKLOAD_IDENTITY_PROVIDER:-}" ]]; then
    : "${PROJECT_ID:?PROJECT_ID is required when GCP_WORKLOAD_IDENTITY_PROVIDER is omitted}"
    : "${POOL_ID:?POOL_ID is required when GCP_WORKLOAD_IDENTITY_PROVIDER is omitted}"
    : "${PROVIDER_ID:?PROVIDER_ID is required when GCP_WORKLOAD_IDENTITY_PROVIDER is omitted}"
    command -v gcloud >/dev/null 2>&1 || {
      echo "gcloud is required to resolve GCP_WORKLOAD_IDENTITY_PROVIDER" >&2
      exit 2
    }
    project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')" || {
      echo "cannot resolve project number for ${PROJECT_ID}" >&2
      exit 1
    }
    export GCP_WORKLOAD_IDENTITY_PROVIDER="projects/${project_number}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
  fi
  if [[ -z "${GCP_SERVICE_ACCOUNT_EMAIL:-}" ]]; then
    : "${PROJECT_ID:?PROJECT_ID is required when GCP_SERVICE_ACCOUNT_EMAIL is omitted}"
    export GCP_SERVICE_ACCOUNT_EMAIL="github-actions-${runtime_environment}@${PROJECT_ID}.iam.gserviceaccount.com"
  fi
  [[ "${GCP_WORKLOAD_IDENTITY_PROVIDER:-}" =~ ^projects/[0-9]+/locations/global/workloadIdentityPools/[a-z][a-z0-9-]{0,31}/providers/[a-z][a-z0-9-]{0,31}$ ]] || {
    echo "GCP_WORKLOAD_IDENTITY_PROVIDER must be a full active provider resource name" >&2
    exit 2
  }
  [[ "${GCP_SERVICE_ACCOUNT_EMAIL:-}" =~ ^[A-Za-z0-9][A-Za-z0-9-]{4,29}@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$ ]] || {
    echo "GCP_SERVICE_ACCOUNT_EMAIL must be a valid service-account email" >&2
    exit 2
  }
  runtime_path="${runtime_environment}/serverless/gcp"
  if [[ "${mode}" == apply ]]; then
    echo "Writing runtime GCP identity to kv/${runtime_path} (values redacted)..."
    VAULT_ADDR="${vault_addr}" vault kv patch -mount=kv "${runtime_path}" \
      GCP_WORKLOAD_IDENTITY_PROVIDER="${GCP_WORKLOAD_IDENTITY_PROVIDER}" \
      GCP_SERVICE_ACCOUNT_EMAIL="${GCP_SERVICE_ACCOUNT_EMAIL}" >/dev/null
  else
    VAULT_ADDR="${vault_addr}" vault kv get -mount=kv -format=json "${runtime_path}" |
      jq -e --arg provider "${GCP_WORKLOAD_IDENTITY_PROVIDER}" --arg account "${GCP_SERVICE_ACCOUNT_EMAIL}" \
        '.data.data.GCP_WORKLOAD_IDENTITY_PROVIDER == $provider and .data.data.GCP_SERVICE_ACCOUNT_EMAIL == $account' >/dev/null || {
          echo "kv/${runtime_path}: runtime identity does not match supplied active values; run --apply" >&2
          exit 1
        }
    echo "kv/${runtime_path}: runtime identity matches (values redacted)"
  fi
fi

echo "Shared GCP Vault role/policy ${mode}: OK"
