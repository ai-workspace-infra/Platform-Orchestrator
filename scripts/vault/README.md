# Vault authorization consumer

The source of truth is the GitOps repository's `security/vault/` YAML tree.
Toolkit reads it at runtime; this directory contains only the reader and
Vault administration entrypoints. The default source is GitOps `main`.
Set `GITOPS_REF` to inspect another branch, tag, or commit, or set `GITOPS_ROOT`
to an already checked out GitOps tree. The source resolver prints the resolved
commit SHA before any Vault operation.

## Layout

- GitOps `security/vault/policies/` contains YAML ACL declarations.
- GitOps `security/vault/roles/` contains YAML JWT role declarations.
- GitOps `security/vault/workload-identities/` contains workload role
  contracts owned and applied by Playbooks, not this shared-role installer.
- GitOps `security/vault/templates/` contains the account-scoped Akamai
  templates.

Vault's API still accepts HCL/JSON. `vault_declarations.py` compiles the
structured YAML into temporary HCL/JSON at runtime, and the installer sends
that output to Vault. No generated declaration is committed. The workload
identity reader can be inspected with `python3 scripts/vault/vault_declarations.py
workload-identity <name>`; it is never passed to the shared JWT installer.
Install the runtime reader dependency with
`python3 -m pip install -r scripts/vault/requirements.txt`; Git is also required.

## Adding a GCP account

For every new account, add the UAT and PROD policy/role declarations. Keep the
account identifier stable and readable (an email-like value is allowed), and
use the same identifier in the role name and Vault paths:

```text
kv/CICD/uat/gcp-bootstrap/<gcp_account_id>
kv/CICD/prod/gcp-bootstrap/<gcp_account_id>
kv/uat/platform/oidc/<gcp_account_id>
kv/prod/platform/oidc/<gcp_account_id>
```

After GCP bootstrap, runtime IaC workflows authenticate with dedicated,
read-only Vault JWT roles:

```text
github-actions-platform-ops-toolkit-uat-gcp-oidc-<gcp_account_id>
github-actions-platform-ops-toolkit-prod-gcp-oidc-<gcp_account_id>
```

These roles can read only the matching environment's WIF provider, audience,
project, and deploy Service Account record. They never read the bootstrap
access token and never change AWS roles or policies.

Review role and policy changes as security-sensitive changes. Do not store
access tokens, private keys, or other secret values in this directory.

## AWS OIDC bootstrap roles

The repository declares separate Vault JWT roles for the controlled AWS OIDC
bootstrap workflow:

```text
github-actions-platform-ops-toolkit-uat-aws-bootstrap
github-actions-platform-ops-toolkit-prod-aws-bootstrap
```

Each role is bound to `aws-oidc-bootstrap.yml`, `refs/heads/main`, and its
matching GitHub Environment (`uat` or `production`). Its policy can read only
the matching environment's short-lived `aws-bootstrap` record and
`iac_state` record. It does not grant access to application credentials.

Apply or check one environment without touching other declarations:

```bash
export VAULT_ADDR=https://vault.svc.plus
bash scripts/create_vault_service_repo_roles.sh --check \
  --role github-actions-platform-ops-toolkit-uat-aws-bootstrap
bash scripts/create_vault_service_repo_roles.sh --apply \
  --role github-actions-platform-ops-toolkit-uat-aws-bootstrap
```

The script provisions the Vault role and policy only. AWS IAM OIDC trust
reconciliation remains a separate, explicitly approved AWS bootstrap action.

## Console PROD image builds

The Portal PROD build role (`github-actions-console-prod`) may read only the
shared `kv/data/CICD` GHCR credentials. Its source refs are `v*`,
`release/v*`, and the Portal-specific `prod-v2-*` release tags. The latter is
an explicit exception for the Web SaaS PROD V2 release lane; it does not grant
host SSH or deployment credentials.

Apply or check only this declaration after review:

```bash
VAULT_ADDR=https://vault.svc.plus bash scripts/create_vault_service_repo_roles.sh \
  --apply --role github-actions-console-prod
```

## Console-only UAT deployment

`github-actions-console-uat-deploy` is separate from the legacy Console CI
roles. It trusts only Portal `console-uat-pipeline.yml` dispatched on `main`
in GitHub Environment `uat`. The workflow checks out a reviewed immutable
release tag after validation; the OIDC caller remains the main workflow.
Its only capability is `read` on `kv/data/uat/serverless/cloudflare`.
No PROD, shared CICD, KV writes, database or other environment access is granted.
The Cloudflare token's own scope remains independently administered; this
declaration does not create or broaden a Cloudflare token.

Apply only this declaration after review:

```bash
VAULT_ADDR=https://vault.svc.plus bash scripts/create_vault_service_repo_roles.sh \
  --apply --role github-actions-console-uat-deploy
```

The existing Console roles and policies are not changed.

## V6 Vault TLS workload identity

The V6 GitHub access and admin roles are regular protected-tag roles in the
shared `auth/jwt` mount. After reviewing their declarations, install or check
them one at a time with the existing targeted role entrypoint:

```bash
bash scripts/create_vault_service_repo_roles.sh --check \
  --role github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-access
bash scripts/create_vault_service_repo_roles.sh --apply \
  --role github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-access
bash scripts/create_vault_service_repo_roles.sh --check \
  --role github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-admin
bash scripts/create_vault_service_repo_roles.sh --apply \
  --role github-actions-platform-ops-toolkit-prod-k3s-v6-vault-tls-admin
```

The `prod-k3s-v6-vault-tls-reader` contract under `workload-identities/` is
different: Playbooks creates it only on `jwt-prod-k3s-v6` after checking the
target cluster and TokenRequest evidence. Never pass that reader to the shared
role installer or create it under `auth/jwt`.

## General apply

Run with an authenticated Vault admin session:

```bash
export VAULT_ADDR=https://vault.svc.plus
export VAULT_TOKEN='hvs.***'
bash scripts/create_vault_service_repo_roles.sh
```

The same entrypoint can also manage the Akamai Cloud/Linode OIDC role. Set the
concrete account name or ID and select the environment:

```bash
export AKAMAI_ACCOUNT_PROD='actual-account'
bash scripts/create_vault_service_repo_roles.sh --apply --env prod
```

The entrypoint defaults to `--check`. Use `--apply` only after review to write
Vault:

```bash
export AKAMAI_ACCOUNT_PROD='actual-account'
bash scripts/create_vault_service_repo_roles.sh --check --env prod
```

When no `AKAMAI_ACCOUNT_UAT` or `AKAMAI_ACCOUNT_PROD` is provided, the entrypoint
keeps its previous behavior and skips dynamic Akamai role management. The
PROD role name is `prod-akamai-iac` (15 characters). The account remains part
of the attached policy name and secret path; it is not concatenated into the
role name. UAT retains its existing account-scoped role naming.

## Akamai Cloud/Linode environment-scoped roles

The PROD role is `prod-akamai-iac`, bound to the `prod` GitHub Environment and
the IaC stage and AI Aggregator workflows on `main`. Its attached policy reads
only the selected account's `LINODE_TOKEN` and the PROD IaC state. `primary`,
`default`, and `main` are not valid account values. Render and publish only
the requested Akamai roles with:

```bash
export VAULT_ADDR=https://vault.svc.plus
export VAULT_TOKEN='hvs.***'
export AKAMAI_ACCOUNT_UAT='actual-uat-account'
export AKAMAI_ACCOUNT_PROD='actual-prod-account'
bash scripts/cloud/bootstrap/Akamai-Cloud/bootstrap_akamai_oidc_roles.sh --apply --env all
```

The script uses the repository and workflow claim bindings, creates read-only
policies for the account's `LINODE_TOKEN` record and environment state record,
and does not write any secret value. Run
`bootstrap_akamai_cloud_kv.sh --apply --env all` separately to write the
`LINODE_TOKEN` value.

## Standalone Observability UAT role

The Observability migration workflow uses the dedicated
`github-actions-platform-ops-toolkit-uat-observability` role. Its JWT is bound
to the `observability-server.yml` workflow on `main` in the GitHub `uat`
environment; its policy grants read access only to the shared `kv/data/CICD`
secret needed for the SSH key and DNS token. It does not inherit the general
UAT role's application-secret write permissions.

After review and merge, apply just this role and its policy from an authenticated
Vault admin session. The targeted mode writes only the selected role and its
referenced policy; it does not run dynamic Akamai role management or deprecated
role cleanup:

```bash
export VAULT_ADDR=https://vault.svc.plus
bash scripts/create_vault_service_repo_roles.sh --apply \
  --role github-actions-platform-ops-toolkit-uat-observability
```

Use `--check --role github-actions-platform-ops-toolkit-uat-observability` to
confirm the declared policy and role already exist in Vault without writing.
