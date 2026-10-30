#!/usr/bin/env bash
# Shared source resolver for Vault administration entrypoints.
# Call vault_gitops_source_init and install vault_gitops_source_cleanup on EXIT.

vault_gitops_source_init() {
  command -v git >/dev/null 2>&1 || { echo "git is required to resolve GitOps Vault declarations" >&2; return 1; }
  command -v python3 >/dev/null 2>&1 || { echo "python3 is required to render Vault API payloads" >&2; return 1; }
  if [[ -n "${GITOPS_ROOT:-}" ]]; then
    [[ -d "${GITOPS_ROOT}/security/vault" ]] || {
      echo "GITOPS_ROOT must contain security/vault" >&2
      return 1
    }
    local source_url
    source_url="$(git -C "${GITOPS_ROOT}" remote get-url origin 2>/dev/null || true)"
    case "${source_url}" in
      https://github.com/ai-workspace-infra/gitops|https://github.com/ai-workspace-infra/gitops.git|git@github.com:ai-workspace-infra/gitops|git@github.com:ai-workspace-infra/gitops.git) ;;
      *) echo "GITOPS_ROOT origin must be ai-workspace-infra/gitops" >&2; return 1 ;;
    esac
  else
    local requested_ref="${GITOPS_REF:-main}"
    local source_tmp
    source_tmp="$(mktemp -d)"
    VAULT_GITOPS_TEMP_ROOT="${source_tmp}"
    git -C "${source_tmp}" init --quiet
    git -C "${source_tmp}" remote add origin "https://github.com/ai-workspace-infra/gitops.git"
    git -C "${source_tmp}" fetch --quiet --depth=1 origin "${requested_ref}"
    git -C "${source_tmp}" checkout --quiet --detach FETCH_HEAD
    GITOPS_ROOT="${source_tmp}"
    export GITOPS_ROOT
  fi
  GITOPS_RESOLVED_SHA="$(git -C "${GITOPS_ROOT}" rev-parse HEAD 2>/dev/null || printf 'working-tree')"
  export GITOPS_RESOLVED_SHA
  echo "Vault declarations: GitOps ${GITOPS_REF:-main} (${GITOPS_RESOLVED_SHA})"
}

vault_gitops_source_cleanup() {
  if [[ -n "${VAULT_GITOPS_TEMP_ROOT:-}" ]]; then
    rm -rf -- "${VAULT_GITOPS_TEMP_ROOT}"
  fi
}
