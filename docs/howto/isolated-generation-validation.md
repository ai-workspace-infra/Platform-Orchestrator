# Isolated generation clean-room validation

This runbook applies the [unified deployment/migration process](https://github.com/ai-workspace-services/.github/blob/main/docs/control-plane-deployment-and-migration.zh.md)
to an explicitly disposable candidate. Serving production state, DNS and writer
ownership remain protected. IaC issue [#462](https://github.com/ai-workspace-infra/iac_modules/issues/462)
tracks the reviewed owner contract.

Use the existing `iac-orchestrator.yml` entry for resource-only candidate cleanup.
The shared `selfhost-orchestrator.yml` production destroy prohibition remains in
place. This is an opt-in GitOps `validation.mode: cleanroom` contract, not a
general production destroy override.

Resolve and record these inputs before dispatch: action (`destroy` for candidate
compute cleanup, `apply` for recreation), environment, exact reviewed target
manifest, full GitOps SHA, full IaC owner SHA, `stage_scope=resources`,
`bootstrap_mode=verify`, and a unique correlation ID. Select an approved immutable
production release ref for the workflow; source code is pinned from reviewed
main commits. Never widen Vault/ref rules to make a run succeed.

The owner validates distinct source/candidate namespaces, canonical state keys,
live state lineages and cloud resource identities, then applies only a saved plan
which deletes one declared candidate instance. The source state is read-only;
retained resources and source state must remain unchanged. Provider backups tied
to the instance block cleanup. Externally retained data backup/restore receipts
must be verified before the mutating dispatch. Missing state, read access or
scope evidence is a failed preflight; do not report it as a successful destroy.

Verify each exact correlated child run and its receipt. Require
`namespace_isolation`, `retained_resources`, `source_unchanged` and convergence
evidence. Preserve the remote backend/state history and recovery objects. A
subsequent normal apply restores the protected render and must emit fresh CMDB;
do not reuse the old address or inventory for host deployment.

| Stage | Execution and acceptance |
| --- | --- |
| Candidate cleanup | Exact compute removed; serving source, retained resources, DNS and backup objects unchanged |
| Clean-room infrastructure | New instance identity, protected render, valid current CMDB and trusted SSH identity |
| First deployment | Fixed Playbooks/GitOps/installer SHA and image digests; actual service/DB/TLS validation |
| Deployment replays 1–3 | Same exact inputs; independent runs; no nonrequired restart/recreation or configuration/schema/data differences |
| First migration | Prebuilt pinned migratectl; read-only source snapshot, restorable target backup, exact preview/plan review, approved additive transaction |
| Migration replays 1–3 | Fresh previews and safe no-op applications; stable all-field summaries, schema and target-only facts |
| Recovery and regression | Isolated representative restore plus real repository regression cases; unexecuted business paths remain NOT_RUN/BLOCKED |
| Await cutover | Evidence archived; no source write transfer or public DNS change without separate manual confirmation |

Record independent run IDs, Asia/Shanghai start/end, source/target identities,
fixed code/tool/image digests, schema/migration checksums, phase, exit code,
failures, repair PRs, retest outcomes and sanitized evidence links. Keep raw
database/state/credential material in controlled storage. No static/local test
result substitutes for the required real deployment and migration replays.
