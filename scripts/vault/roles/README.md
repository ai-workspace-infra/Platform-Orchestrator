# Vault JWT role declarations

Each JSON file in this directory is one concrete Vault JWT role. The filename
must match `role_name`; `description` documents the trust boundary and is
removed before the payload is sent to Vault. Policies are stored separately in
`../policies/` and referenced by `token_policies`.

To add another GCP account, add one UAT role JSON and one PROD role JSON with
the account identifier in the filename, role name, policy name, and Vault KV
paths. `gcp_account_id` may be an email-like readable identifier, but must not
contain `/`.

The parent `scripts/create_vault_service_repo_roles.sh` is intentionally only
the orchestration entrypoint. Review changes to these declarations as Vault
authorization changes.

Kubernetes workload identities configured on dedicated JWT mounts belong in
`scripts/vault/workload-identities/`; they are not shared GitHub OIDC roles and
must not be applied by this installer.
