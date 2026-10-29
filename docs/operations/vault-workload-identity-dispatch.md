# Vault workload identity dispatch catalog

This catalog documents the `workflow_dispatch` contract for
`.github/workflows/vault-workload-identity.yml`. Recheck the workflow and its
called scripts whenever this catalog or workflow changes.

## Inputs

| Input | Type | Required values | Meaning |
| --- | --- | --- | --- |
| `mode` | choice | `configure`, `verify` | `configure` creates the declared dedicated JWT mount, exact-path policy, and reader role; `verify` runs only the workload authorization probes. |
| `gitops_tag` | string | Immutable stable `v*` tag | Selects the reviewed GitOps declaration and evidence contract. |
| `operation_path` | string | Relative declaration path inside the selected GitOps checkout | Selects the one workload identity operation to resolve and validate. |
| `environment` | choice | `sit`, `uat`, `prod` | Selects the protected GitHub Environment and must match the declaration. |
| `playbooks_sha` | string | Full 40-character commit on `main` | Pins the reviewed Playbooks owner action used to configure or verify the identity. |

There are no defaults. The workflow has no DNS or Flux reconciliation input.

## Enforced preconditions

- The dispatch must run from a protected `refs/tags/v*` ref.
- The Playbooks commit must be reachable from `main`, and the GitOps tag must
  be an immutable release reachable from `main`.
- The selected declaration is path-confined to the GitOps checkout and must
  pass schema and bootstrap/IaC artifact provenance checks.
- The requested environment must match the declaration. The target provider,
  node, Vault roles, secret selectors, identity mount, audience, service
  accounts, exact allowed path, and denied path come from that declaration.
- The IaC receipt and CMDB checksum are verified before resolving the provider
  host key. The owner action checks the target cluster identity before making
  a configuration change.
- `configure` obtains the declared restricted administrator identity;
  `verify` does not request it. Both modes keep credentials out of receipts.
- The workload owner tests the declared allowed record and rejects the
  declared denied path, wrong audience, and wrong service account.

## Operational boundary

`configure` writes only the dedicated mount, the exact reader policy, and its
role. It does not change GitOps resources, enable ESO/TLS synchronization,
deploy application services, or change DNS. Releasing ESO and TLS synchronization
is a separate reviewed step after the redacted allow/deny evidence is accepted.
