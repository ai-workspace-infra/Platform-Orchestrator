# Vault workload identity dispatch catalog

This catalog documents the `workflow_dispatch` contract for
`.github/workflows/vault-workload-identity.yml`. Recheck the workflow and its
called scripts whenever this catalog or workflow changes.

## Inputs

| Input | Type | Required values | Meaning |
| --- | --- | --- | --- |
| `mode` | choice | `configure`, `verify` | Configure the JWT identity or run authorization probes. |
| `gitops_ref` | string | Optional, defaults to `main` | Selects the GitOps declaration; the resolved commit is recorded for the run. |
| `operation_path` | string | Relative declaration path inside the selected GitOps checkout | Selects the one workload identity operation to resolve and validate. |
| `environment` | choice | `sit`, `uat`, `prod` | Selects the protected GitHub Environment and must match the declaration. |
| `playbooks_sha` | string | Full 40-character commit on `main` | Pins the reviewed Playbooks owner action used to configure or verify the identity. |

GitOps defaults to `main`; the workflow has no DNS input. Flux follows its declared source and path independently.

## Enforced preconditions

- The dispatch runs from protected `refs/heads/main`; operation and environment are selected through workflow_dispatch inputs.
- The Playbooks commit must be reachable from `main`, and the selected GitOps commit must be reachable from `main`.
- The selected declaration is path-confined to the GitOps checkout and must
  pass schema and bootstrap/IaC artifact provenance checks.
- The requested environment must match the declaration. The target provider,
  node, Vault roles, secret selectors, identity mount, audience, service
  accounts, exact allowed path, and denied path come from that declaration.
- The IaC receipt and CMDB checksum are verified before resolving the provider
  host key. The owner action checks the target cluster identity before making
  a configuration change.
- `configure` obtains the declared restricted administrator identity;
  `verify` does not request it. All modes keep credentials
  out of receipts.
- The restricted administrator can read only the dedicated V6 auth config and
  role in addition to its existing mount/policy scope, so configure inspects
  existing state before making any change. Existing unreviewed values fail closed.
- A redacted stage receipt is uploaded whenever the owner creates one, including
  owner failures; the workflow then remains failed after evidence upload.
- A separate `verify` run checks the declared allowed record and rejects the
  declared denied path, wrong audience, and wrong service account.

## Operational boundary

`configure` writes only the dedicated mount, exact reader policy, and role. `verify` checks allowed and denied access.
