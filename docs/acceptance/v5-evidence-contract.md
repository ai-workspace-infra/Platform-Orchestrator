# V4 → V5 acceptance: first owner-first delivery

Task: [V4→V5 干净重建与 Selfhost 全流程验收](codex://threads/01a1691f-61fc-7843-9e1d-e04d1bfe900d).
The existing `environment-data-operations.yml` now contains one optional
post-migration V5 job matrix; no new workflow is added. SSH → Playbook → Role is the
first execution route. [中文验收矩阵](v5-matrix.zh.md) 与 `v5-matrix.json`（v2）记录同一份 23 组清单、
多阶段映射、必需断言及有时间边界的历史/采样状态，供后续审阅。
The matrix records the stage DAG for
later migration-dispatch integration; it does not implement or enable that DAG.
Every suite listed is required for final acceptance. A stage approval never
substitutes for the receipt from its resource owner.

## Existing paths and ownership

Toolkit already has `import_receipt.py`, the selfhost baseline-state reader,
`selfhost-orchestrator.yml`, and `web-saas-k3s-orchestrator.yml`. Import receipts
bind several identities but are specific to import semantics; the baseline
reader lacks the complete environment/owner/SHA/attempt/check set. Neither is
replaced or silently redirected by this change. Existing serverless summary
validation stays separate. New validation is offline control-plane logic;
SSH, SQL and Kubernetes observations stay in Playbooks' `v5_readonly_acceptance`
role. GitOps keeps declared state; IaC keeps cloud/DNS/CMDB facts.

## Strict offline contract

Call `.github/scripts/acceptance/verify_receipt.py --request REQUEST.json
--receipt RECEIPT.json --evidence-root DIRECTORY`.

Trusted request keys are exactly: environment (`sit|uat|prod`), cluster, host_id,
owner (`playbooks|iac_modules|platform-ops-toolkit`), workflow, parent_run_id,
parent_run_attempt, child_run_id, child_run_attempt, artifact_id, toolkit_sha,
gitops_sha, iac_sha, playbooks_sha, release_sha, artifact_digest, required_checks,
not_before, not_after. IDs/attempts are positive decimal strings, SHAs are full
40-character lowercase hex, artifact_digest is `sha256:` plus 64 lowercase hex.
Required checks are a nonempty unique subset of V5-01…V5-23. Timestamp bounds
come from trusted execution metadata; they are UTC ISO timestamps.

Receipt keys are exactly schema_version (`v5-acceptance/v1`), identity (all
request identity keys, excluding checks/time bounds), started_at, finished_at,
checks, result. Every check has exactly id, status, evidence, sha256. Check IDs
must equal the requested set exactly once. Every required status and result
must equal PASS; PARTIAL, FAIL, SKIPPED, NOT_RUN, UNKNOWN, contradictory results,
missing/extra fields and duplicate JSON keys block. Times must be within the
trusted window. Evidence must be a nonempty regular file under the artifact
root with an exact SHA-256; traversal and symlinks are forbidden. CLI failures
print no raw payload or traceback. Producer failures must also emit sanitized
results where possible; transport/crash/missing artifacts block regardless.
No exception waiver is implemented: exceptions require a separately reviewed,
scoped assertion, never a generic skip.

The validator does not authenticate GitHub or prove artifact provenance on its
own. Future caller integration MUST resolve exact child run + attempt + owner
workflow/repository + immutable artifact ID/digest using authenticated API
metadata, verify the download/archive digest before extraction, and build the
trusted request independently. A receipt copied into its own request is not
trusted evidence. OCI release digest and download archive digest must be
verified separately by that adapter. The optional same-workflow matrix uses the independently validated automatic
report gate described in `v5-environment-data-matrix.md`; the generic cross-run
receipt caller is not yet enabled; this is not a
production gate cutover or UAT acceptance claim.

Manual SSH observations use `v5-readonly-observation/v1`, not invented GitHub
run IDs or dispatch receipts. They cannot release migration/cutover stages.
Keep JUnit/Allure fixtures separate from runtime evidence. Allure results are
raw result files until a report renderer is run.

## Verification and remaining gates

Offline adversarial coverage includes every identity field, missing/invalid
JSON/artifacts, wrong SHA/digest, missing/duplicate checks, non-PASS statuses,
unsafe paths, empty/tampered/symlink evidence and invalid execution windows.
Run with pytest and `--junitxml` / `--alluredir`; preserve artifacts outside the
repository rather than committing synthetic reports as runtime acceptance.

Remaining work: reviewed owner producers and full schema publication, exact
artifact downloader/caller integration, UAT receipt round-trip, all 23 actual
suite implementations, independent cloud/CMDB identity, Vault equality,
Grafana queries/alerts, real current-candidate business E2E, three-round
idempotency and controlled restore. Do not merge/promote the new route as fully
accepted until owner→caller→UAT evidence exists. Existing routes remain intact.
