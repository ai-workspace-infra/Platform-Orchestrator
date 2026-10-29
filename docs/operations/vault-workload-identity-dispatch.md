# Vault workload identity dispatch catalog

This catalog documents the `workflow_dispatch` contract for
`.github/workflows/vault-workload-identity.yml`. Recheck the workflow and its
called scripts whenever this catalog or workflow changes.

## Inputs

| Input | Type | Required values | Meaning |
| --- | --- | --- | --- |
| `mode` | choice | `configure`, `verify`, `release-root`, `release-eso`, `release-identity` | `configure` creates the dedicated JWT mount, exact-path policy, and reader role; `verify` runs authorization probes; release modes open one bounded V6 Flux gate. |
| `gitops_tag` | string | Immutable stable `v*` tag | Selects the reviewed GitOps declaration and evidence contract. |
| `operation_path` | string | Relative declaration path inside the selected GitOps checkout | Selects the one workload identity operation to resolve and validate. |
| `environment` | choice | `sit`, `uat`, `prod` | Selects the protected GitHub Environment and must match the declaration. |
| `playbooks_sha` | string | Full 40-character commit on `main` | Pins the reviewed Playbooks owner action used to configure or verify the identity. |

There are no defaults. The workflow has no DNS input. Release modes apply only the
reviewed V6 `config-prod` source and root from the pinned tag; the root, ESO, and
Vault TLS identity stages each have a separate dispatch.

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
  `verify` and the release modes do not request it. All modes keep credentials
  out of receipts.
- The workload owner tests the declared allowed record and rejects the
  declared denied path, wrong audience, and wrong service account.

## Operational boundary

`configure` writes only the dedicated mount, the exact reader policy, and its
role. `release-root` enables only the V6 management source and root;
`release-eso` additionally opens ESO; `release-identity` additionally opens
the Vault TLS reader identity source and ServiceAccount gate. These release
modes do not configure Vault, enable TLS synchronization, deploy application
services, or change DNS. TLS synchronization remains a later separately
reviewed release after the Vault allow/deny verification is accepted.
