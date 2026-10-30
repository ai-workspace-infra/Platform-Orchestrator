# Selfhost Orchestrator operational input catalog

Source: `.github/workflows/selfhost-orchestrator.yml`. V6 uses a separate cold-bootstrap route; legacy profiles keep their existing routing.

| Input | Type | Required | Default | V6 behavior |
| --- | --- | --- | --- | --- |
| `runner_type` | choice | true | `ubuntu-latest` | ubuntu-latest |
| `deploy_tag` | string | false | `` | Must be blank; unused by V6 |
| `source_ref` | string | false | `` | V6 requires JSON keys `gitops`, `playbooks`, `iac`; GitOps selects a reviewed tag, owners select a branch or tag, resolved once to SHAs. Legacy routes retain their plain-ref input. |
| `offline_mode` | choice | false | `off` | off |
| `source_host` | string | true | `install.svc.plus` | Ignored by V6; ineffective control |
| `source_domain_base` | string | true | `svc.plus` | Ignored by V6; ineffective control |
| `target_domain_base` | string | true | `onwalk.net` | Ignored by V6; ineffective control |
| `observability_endpoint` | string | false | `https://observability.svc.plus` | Ignored by V6; ineffective control |
| `xray_exporter_image` | string | false | `` | Must be blank; unused by V6 |
| `operation` | choice | true | `plan` | plan / infra+common / deploy+common+paused cluster |
| `target_domains` | choice | true | `web-saas` | web-saas |
| `open_platform_service` | choice | true | `none` | none |
| `cloud_provider` | choice | true | `gcp-cloud` | akamai-cloud |
| `cloud_account` | string | false | `` | manbuzhe2026 |
| `akamai_account` | string | false | `` | blank or manbuzhe2026 |
| `include_external_agent_proxy` | boolean | false | `True` | false |
| `instance_plan` | choice | true | `2C4G` | 2C4G |
| `agent_proxy_plan` | choice | true | `1C2G` | Ignored by V6; ineffective control |
| `dns_mode` | choice | true | `none` | none |
| `vault_env_path` | string | true | `uat` | prod-v6 |
| `skip_stripe_catalog` | boolean | false | `False` | true |
| `agent_controller_url` | string | false | `` | Must be blank; unused by V6 |
| `vault_addr` | string | false | `` | Must be blank; unused by V6 |
| `xconnect_gateway_ref` | string | false | `tw-xconnect.svc.plus` | Ignored by V6; ineffective control |
| `existing_target_host` | string | false | `` | Must be blank; unused by V6 |

## Hidden rules and execution evidence

Dispatch V6 only at a reviewed root release tag. The GitOps tag must contain all six initially self-pinned sources, nine Flux Kustomizations and eight HelmReleases, suspended. Each later unit may use its own independent ref and chart pin.

## Component selection and frozen execution

The workflow has 25 dispatch inputs. V6 uses the existing `source_ref` as a structured
selection rather than adding more inputs or editing component SHAs in environment config:

```json
{"gitops":"<reviewed-gitops-tag>","playbooks":"main","iac":"<reviewed-iac-branch-or-tag>"}
```

Use `refs/heads/<branch>` or `refs/tags/<tag>` if a short name is ambiguous.
Both owner repositories are fetched without executing their code. Preflight verifies
the selected commit matches the checkout, belongs to `origin/main` history, and has a
clean tree. Unmerged feature commits, missing refs, ambiguous names and incomplete
selections fail before IaC dispatch or Vault login. Main ancestry establishes the merge
boundary; it does not establish that this component combination has passed integration
or runtime acceptance.

All downstream jobs consume `v6-resolve.outputs.iac_sha` and `playbooks_sha`.
The log records each requested ref and resolved SHA. A branch moving after resolution
does not change the code used by downstream jobs in that attempt. A complete rerun
resolves branch inputs again; use immutable tags to repeat the previous candidate and
revalidate receipts whenever the resolved candidate changes.

### Workflow literal audit

| Previous literal | Current source / reason |
| --- | --- |
| IaC / Playbooks commit SHAs in environment config | Dispatch selection, resolved to SHA before execution |
| Environment, account, IaC selectors, node and correlation suffix in YAML | Validated GitOps global scope and selected profile outputs |
| Vault URL, role and record paths in YAML | Reviewed `bootstrap_vault` identity binding in the selected control-plane profile; no caller-provided secret path |
| Parent-wide environment routing and unused service KV variables | Removed; dispatched child workflows own their environment resolution and credential scope |
| Action versions, repository identities, protocol field names, timeouts | Retained implementation/security contracts; not environment or component-version selection |
| Existing `prod-v6` route, supported operations, protected tags and DNS gate | Retained authorization/compatibility boundary. Changing the selector alone does not implement a different generation; generic owner capability must exist first |

V6 `dns_mode=none` protects canonical records. Dedicated batch records require their
own explicit IaC DNS-owner operation and exact target address; this cleanup performs
no DNS update and does not add a DNS stage.

`plan` runs IaC plan; `infra` applies isolated resources and runs common identity checks; `deploy` applies resources and verifies paused bootstrap. No migratectl, SQL schema upgrade, restore, DNS or writer handoff runs in this path. Source host, source/target domain bases, telemetry override, agent plan and XConnect inputs are ignored, not effective V6 configuration.

IaC owns resources, protected volume CMDB and provider SSH identity attestation. Playbooks owns empty-disk preparation, K3s/Flux and observed paused-state verification. This control plane selects fixed SHAs, dispatches owners and checks evidence.

The 100 GB independent data volume mounts at /data; local-path storage is /data/k3s/storage. K3s depends on the mount. Only creates/no-ops are allowed; update/delete/replace, wrong disk owner, unknown signatures, nonempty mountpoints or active release graphs fail closed.

Dedicated Vault roles accept PROD OIDC from the exact reviewed workflows on main. The one-time Playbooks system-admin initializer creates those roles and the V6 SSH KV binding. No administrator token is available to CI.

The IaC child binds correlation, target path, GitOps/IaC SHAs, action, run attempt and artifact checksum. A public PAUSED_BOOTSTRAP_VERIFIED receipt records actual node/cluster UIDs, installed version, mount UUID and observed declaration identities/specs. This proves paused bootstrap only.

On failure retain the candidate/disk, inspect the exact run before retrying, fix through owner PRs, release and retest. V5 remains untouched. Business identity/RBAC/storage/secret and readiness checks are required before activating workloads.

Target preparation: [GitOps V6 PR](https://github.com/ai-workspace-infra/gitops/pull/658).

Platform-Orchestrator defaults to `main`. Select the environment, provider, account,
resource profile, DNS mode and operation through `workflow_dispatch`. Record the
resolved control commit and owner SHAs in each run. Infrastructure owner repositories
default to `main`; business artifacts retain their independent release versions.
Dedicated Vault identities bind the exact approved workflow paths to
`refs/heads/main`. Apply the reviewed role declarations before dispatching from main;
changing the files does not update live Vault roles.

The first V6 apply created and converged only the three approved resources.
Host bootstrap stopped before SSH because console binary frames were coerced to
object strings. Retain that candidate and disk. The caller must pin the reviewed
IaC decoding fix before retrying, and a fresh plan must show no resource changes.
No console trust or fingerprint comparison may be bypassed to resume.

Canonical cloud-init HOST KEY KEYS frames and fixed read-only provider scrollback
controls are supported by the reviewed IaC owner. A complete Ed25519 wire key and
matching full fingerprint remain mandatory; unframed, truncated or conflicting
keys are rejected. No guest command or credential is sent through the console.

After verified IaC delivery and SSH identity, the Playbooks owner automatically
runs `vhosts/common` with `tasks_from: node_bootstrap.yml` before data-disk and
K3s roles. Runtime/static hostname, cloud-init persistence and local resolution
must match the canonical IaC node name. Existing K3s node/PV affinity and active
Flux checks fail before hostname changes. `COMMON_NODE_VERIFIED` is mandatory
in the final receipt; a business FQDN must remain an alias, never the node name.

Both V6 apply paths automatically run common: infra selects phase=common with disk initialization disabled; deploy selects phase=cluster and continues storage/K3s only after common succeeds. Plan does not execute host roles.
