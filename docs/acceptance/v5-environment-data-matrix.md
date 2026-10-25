# V5 automatic report → existing Environment Data Orchestrator

The only workflow change is one optional `post_migration_v5` host matrix in
`.github/workflows/environment-data-operations.yml`. No new workflow is added;
Selfhost stage workflows are unchanged. Use its existing workflow_dispatch or
workflow_call entry and nonsecret `config_json.post_migration_v5` plan. This
matrix runs after the selected data executor succeeds, not before migration.
It does not repeat migration, provision resources, restart services, switch
writers, or change DNS. Omit the plan to preserve existing callers.

The request gate requires a supported preceding mode (`migrate`, `upgrade`,
`selfhost_verify`, or explicit `core_users` copy), exact environment, all 23
required checks, unique targets and full immutable source SHAs. Existing mode,
PROD reviewer/tag, UAT-only and data-operation gates remain in force. Config
cannot contain secrets or execution commands. No standalone acceptance mode,
new workflow or new dispatch inputs are introduced.

## Nonsecret plan contract

`post_migration_v5` has `schema_version: v5-post-migration/v1`, environment,
`toolkit_sha` equal to this dispatched workflow's SHA, full gitops_sha,
iac_sha, playbooks_sha, plus infra_head_sha, infra_run_id, infra_run_attempt,
cmdb_artifact_id, cmdb_artifact_name, explicit HTTPS vault_addr,
`required_checks: [V5-01, ..., V5-23]`, and targets.

Each target has host (exact CMDB inventory name), host_id (cloud instance ID
as decimal string), machine_id, independently trusted known_hosts (public key
records, never a scan accepted during the same connection), namespace,
database_pod, database_user, database_name, schema, expected_agents,
source_name and source_namespace. The explicit Vault URL must match the trusted repository/environment `VAULT_ADDR`
variable; missing/mismatched configuration blocks before OIDC credentials. No
target, credential or environment fallback.
Keep runtime facts in the IaC/CMDB evidence and scoped request, not GitOps.
GitOps retains desired state. The plan is a reviewed operation request, not a
receipt or proof that a migration/recovery happened.

## Execution and final gate

Before owner credentials, Toolkit retrieves the exact infrastructure artifact
by ID, verifies repository/run/attempt/name/head SHA, completed successful run
and ZIP digest, then reads only the unique bounded `cmdb.json` member. Its producer
`source_shas.iac_sha` and `source_shas.gitops_sha` must match the reviewed plan;
older artifacts lacking this provenance fail closed and require an IaC-owner
producer update, never caller-added or inferred proof. The
Playbooks action checks its actual immutable checkout, exact CMDB host and
environment, then calls the same SSH → Playbook → Role route using strict
known_hosts and an ephemeral SSH agent. It returns failure when required
business checks are incomplete. Per-target artifacts include Markdown, JUnit,
allowlisted JSON, checksums and the sanitized Playbook log even after failure.

The Toolkit report gate separately verifies all file hashes, exact current
run/attempt/host/environment/Playbooks/GitOps identities, verified scope and
all 23 checks PASS. Artifact upload or workflow success alone cannot release.
The existing verdict also rejects a failed or skipped requested matrix.
PARTIAL, NOT_RUN, UNKNOWN and SKIPPED are business JUnit failures. Effectiveness
pytest results are separate and never become business acceptance.

This is a same-workflow job boundary: reports do not cross to an uncorrelated
child run. The generic cross-workflow `v5-acceptance/v1` receipt validator stays
available but is not silently replaced by the report schema. Any future separate
dispatch must additionally bind child artifact ID/digest and run metadata.

## Enablement prerequisites and rollout

Merge/review the Playbooks producer first, select its new immutable SHA in the
reviewed plan, verify exact IaC CMDB artifact and trusted SSH facts, validate
Vault OIDC authorization for this existing workflow and environment path, then
run UAT with the same owner adapter. Do not widen Vault policy or bypass claims
on a 403. PROD remains read-only for this matrix; production migration/writer
handoff/rebuild/recovery still require their separate approvals and UAT proof.

Current status: automatic Role report and rejection behavior tested on the
current V5 K3s via SSH. Actions execution, UAT owner→caller round-trip and full
23-suite acceptance remain NOT_RUN; the current observer intentionally reports
NOT_RUN for unimplemented suites and cannot grant full acceptance. No operational
GitHub dispatch has been performed merely to validate this implementation.
