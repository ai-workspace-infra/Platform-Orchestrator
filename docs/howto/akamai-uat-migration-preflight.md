# Akamai UAT migration preflight

Entry updated: dispatch Toolkit `environment-data-operations.yml`, mode `akamai_preflight`,
environment `uat`, config_json.account set explicitly. The query executor is the IaC `akamai-state-preflight` composite action at a fixed
owner SHA; Toolkit owns the workflow and authorization. Historical workflow versions
remain retrievable at immutable SHAs for rollback.
Account `manbuzhe2026` below is an example, not a hardcoded runtime default.

This manual workflow inventories the six UAT Akamai namespaces, the historical
shared state, and matching Linode instances/firewalls. It is read-only: it runs
Terraform backend initialization plus `terraform show -json`, S3 object-version
metadata reads, and Linode API `GET` requests. Terraform JSON is parsed in memory
and projected to allowlisted identity fields; the raw output is never printed or
uploaded. It never
runs a Terraform plan/apply, state import/move/remove/push, or resource deletion.

## Scope and state identities

The workflow passes `iac/catalog.yaml` from the selected GitOps SHA to the IaC owner.
The same target loader and canonical identity generator are used by deployment and
preflight. Target references declare environment, project, provider, concrete account,
namespace, lifecycle and a resource manifest. Deployment selects active targets;
preflight includes read-only migration/retired targets for the selected UAT account.
No namespace list or lifecycle registry is maintained in the provider implementation.

Historical shared-state sources live separately in the catalog with exact keys,
read-only lifecycle and immutable source provenance. The existing retirement report
supports one historical shared source per selected account/scope and fails closed
if multiple shared origins are selected. This does not limit the number of target
namespaces. The old Kubernetes UAT target is inspected as a migration target, without
returning it to the active deployment set.

Before reading backend state, the query owner verifies the actual Linode username.
Reports distinguish all retained state bindings from provider resources matched by
ID/label. A missing provider match is ambiguous and never grants state deletion.

## Run

First merge the implementation PR to `main`. The UAT Vault JWT role is bound to
the workflow path and `refs/heads/main`; after merge, update that role using the
normal administrator bootstrap process so the new workflow is in its
`job_workflow_ref` allowlist:

```bash
export VAULT_ADDR='https://vault.svc.plus'
export VAULT_TOKEN='<Vault policy/role administrator token>'
export AKAMAI_ACCOUNT_UAT='manbuzhe2026'
bash scripts/cloud/bootstrap/Akamai-Cloud/bootstrap_akamai_oidc_roles.sh --apply --env uat
```

Then open **Actions → Akamai UAT migration preflight → Run workflow**, select
`main`, and start it. The workflow is `workflow_dispatch` only and has no
mutable operation inputs. It uses GitHub OIDC to read the UAT Akamai token and
state KV values, checks out `gitops/main` and `iac_modules/main`, and runs the
read-only script. No workflow run is started by this change.

The run summary and seven-day JSON artifact contain only the state keys,
resource addresses/types/IDs/labels, instance region/plan/status, S3 version
metadata, mapping counts, and recommendations. Terraform state bodies and
credentials are never printed or uploaded.

## Per-namespace result

| Status | Meaning | Suggested next step |
| --- | --- | --- |
| `existing-in-legacy-state` | Linode instance ID and label match the old shared state | Review a one-to-one state adoption/move plan; do not create a duplicate |
| `existing-in-namespace-state` | The resource is already present in its canonical namespace state | Review the plan for drift; do not import or recreate it |
| `existing-unmanaged` | A matching instance exists in Linode but is absent from the old state | Review ownership, then plan a controlled import |
| `absent` | No matching instance, firewall, or old state resource was found | Review a one-namespace create plan |
| `ambiguous` | Duplicate labels/IDs, partial resources, or state/API disagreement | Stop and reconcile manually |

Any repeated expected label, a resource mapping to multiple namespaces, the old
`observability.svc.plus` source in any Akamai manifest/state, or `open-platform`
inside the cleanup set fails the run. `open-platform` is always reported as
persistent and not cleanup eligible.

## Legacy state retirement preview

`retirement_plan` includes the exact legacy key, current and prior S3 object
version metadata, whether versioning is enabled, a suggested archive key, and
an address-by-address mapping to the six target states. It reports counts for
one-to-one, unmapped, duplicate, and wrong-namespace mappings. The suggested
archive key is:

```text
terraform/archive/uat/platform-ops-toolkit/akamai-cloud/manbuzhe2026/selfhost/terraform.tfstate
```

The workflow only reads S3 version listings and archive object headers. It does
not copy or delete the state object. A backup prerequisite is satisfied only
when bucket versioning is enabled, the current object has a non-null VersionId,
and either an earlier object version exists or the suggested archive object is
present with matching size and ETag. The output reports these facts separately;
it never creates the archive copy.

Legacy state retirement is a later, separately reviewed phase. It is blocked
until all six namespace plans show `0 to add, 0 to change, 0 to destroy`, the
migration acceptance is recorded, the original
`ssh ubuntu@observability.svc.plus` host remained unchanged through acceptance,
and the state backup/version prerequisite is satisfied. This PR and workflow
never run `terraform state rm` or retire the legacy object.

### Future auditable retirement workflow interface

A future retirement workflow should be a separate `workflow_dispatch` workflow
with a fixed legacy key/account, a required expected current S3 VersionId, a
verified archive key/version/ETag, the six reviewed plan-run references, the
migration acceptance record, and evidence that the original observability host
was unchanged. Its first job should be read-only and regenerate the exact
one-to-one address mapping. A second job should require the protected
`uat-state-retirement` GitHub Environment approval, re-check the source object
VersionId and all six gates, and derive addresses only from the reviewed
mapping artifact. It must reject `open-platform`, unmapped resources, duplicate
identities, changed object versions, and user-supplied state addresses. Any
future state removal/archive action requires its own reviewed implementation;
this PR does not implement that workflow or grant a deletion path.
