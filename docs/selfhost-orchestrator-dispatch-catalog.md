# Selfhost Orchestrator operational input catalog

Source: `.github/workflows/selfhost-orchestrator.yml`. V6 uses a separate cold-bootstrap route; legacy profiles keep their existing routing.

| Input | Type | Required | Default | V6 behavior |
| --- | --- | --- | --- | --- |
| `runner_type` | choice | true | `ubuntu-latest` | ubuntu-latest |
| `deploy_tag` | string | false | `` | Must be blank; unused by V6 |
| `source_ref` | string | false | `` | Required reviewed GitOps v* tag; owners independently pinned |
| `offline_mode` | choice | false | `off` | off |
| `source_host` | string | true | `install.svc.plus` | Ignored by V6; ineffective control |
| `source_domain_base` | string | true | `svc.plus` | Ignored by V6; ineffective control |
| `target_domain_base` | string | true | `onwalk.net` | Ignored by V6; ineffective control |
| `observability_endpoint` | string | false | `https://observability.svc.plus` | Ignored by V6; ineffective control |
| `xray_exporter_image` | string | false | `` | Must be blank; unused by V6 |
| `operation` | choice | true | `plan` | plan / infra / deploy; deploy creates resources and paused cluster |
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

Dispatch V6 only at a reviewed root release tag. The GitOps tag must contain all six initially self-pinned sources, six Flux Kustomizations and seven HelmReleases, suspended. Each later unit may use its own independent ref and chart pin.

`plan` runs IaC plan; `infra` applies isolated resources; `deploy` applies resources and verifies paused bootstrap. No migratectl, SQL schema upgrade, restore, DNS or writer handoff runs in this path. Source host, source/target domain bases, telemetry override, agent plan and XConnect inputs are ignored, not effective V6 configuration.

IaC owns resources, protected volume CMDB and provider SSH identity attestation. Playbooks owns empty-disk preparation, K3s/Flux and observed paused-state verification. This control plane selects fixed SHAs, dispatches owners and checks evidence.

The 100 GB independent data volume mounts at /data; local-path storage is /data/k3s/storage. K3s depends on the mount. Only creates/no-ops are allowed; update/delete/replace, wrong disk owner, unknown signatures, nonempty mountpoints or active release graphs fail closed.

Dedicated Vault roles accept only PROD OIDC from the exact reviewed workflows on v* tags. The one-time Playbooks system-admin initializer creates those roles and the V6 SSH KV binding. No administrator token is available to CI.

The IaC child binds correlation, target path, GitOps/IaC SHAs, action, run attempt and artifact checksum. A public PAUSED_BOOTSTRAP_VERIFIED receipt records actual node/cluster UIDs, installed version, mount UUID and observed declaration identities/specs. This proves paused bootstrap only.

On failure retain the candidate/disk, inspect the exact run before retrying, fix through owner PRs, release and retest. V5 remains untouched. Business identity/RBAC/storage/secret and readiness checks are required before activating workloads.

Target preparation: [GitOps V6 PR](https://github.com/ai-workspace-infra/gitops/pull/658).

V6 root releases use SemVer prerelease tags such as `v6.0.0-bootstrap.1`.
The reviewed repository tag ruleset in
`.github/policies/prod-k3s-v6-release-tags.json` prevents updates/deletion in
that narrow namespace. Both preflight and Vault require protected tag claims;
the V6 role does not accept arbitrary v* releases or main. Tag creation remains
a deliberate operator action from the CI-passing merged commit.

The first V6 apply created and converged only the three approved resources.
Host bootstrap stopped before SSH because console binary frames were coerced to
object strings. Retain that candidate and disk. The caller must pin the reviewed
IaC decoding fix before retrying, and a fresh plan must show no resource changes.
No console trust or fingerprint comparison may be bypassed to resume.

Canonical cloud-init HOST KEY KEYS frames and fixed read-only provider scrollback
controls are supported by the reviewed IaC owner. A complete Ed25519 wire key and
matching full fingerprint remain mandatory; unframed, truncated or conflicting
keys are rejected. No guest command or credential is sent through the console.
