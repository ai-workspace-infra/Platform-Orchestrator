# Dev create to K3s bootstrap handoff

The Dev host lifecycle invokes bootstrap only for `operation=create`, after the
IaC owner and runtime receipt summary succeed. Plan, resize and destroy never
implicitly bootstrap. There is no user skip-bootstrap input. Failed IaC,
receipt verification or bootstrap fails the run rather than issuing completion.

The real IaC summary artifact contains `summary.json`, `inventory.json` (a mapping
keyed by target ID) and `summary.md`. Its receipt_artifact_id and
inventory_artifact_id are the same artifact ID. The original summary SHA binds
the aggregate; each resources receipt binds its public target inventory digest,
and deploy_matrix is derived from the same inventory. The Toolkit reuses the
IaC owner's `iac-receipt-verify` action, then selects the unique Dev target
mapping byte-equivalently into `cmdb.json` for the existing Playbooks wrapper.
No address or instance ID is invented from declarations. This selection has no
cloud, SSH, Ansible or Vault access.

Verification and selection are steps inside the existing IaC summary job, so
the executed resources-scope create path is gate -> prepare -> resources ->
summary (including receipt verification) -> bootstrap, five stages. At workflow
boundaries the Dev caller has three jobs. The generic IaC orchestrator keeps its
existing unselected bootstrap/account/destroy branches; they are not newly
claimed as executed Dev-create acceptance.

## Immutable dependencies

- IaC #476/#477 source: `20e0b9828e9b078dad85fd470ad3df53c8ebfeda`. The #477 fix
  preserves only four explicit public Dev bootstrap role inputs in the sanitized
  runtime bundle; without it the real bundle lacks required node/version/mode
  inputs and bootstrap must fail, not fabricate defaults.
- GitOps #600/#603 provides the single Dev target and explicit role metadata.
- Playbooks #803/#805 reusable wrapper:
  `e4607530b545ccf09e4045113afeb644b067823e`, internally pinning its validated
  execution source to `4a5dbb8e1240a096e7818f1da6a925569a3da7ea`.

These are pending infrastructure control-plane dependencies, not merged main
implementations. Review and merge the producer/owner/caller changes in dependency
order and retain/review exact source pins before operating. Infrastructure
control-plane availability on main is distinct from the business feature
workflow: unmerged business PR -> isolated SIT -> authorized business merge main
-> independent UAT namespace on the same non-production cluster.

## Bootstrap Vault caller binding

The callee's fixed role remains `github-actions-playbooks-dev-k3s-bootstrap`.
Bind repository `ai-workspace-infra/platform-ops-toolkit`, environment `dev`,
`ref=refs/heads/main`, and caller workflow_ref
`ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-host-lifecycle.yml@refs/heads/main`.
Bind job_workflow_ref exactly to
`ai-workspace-infra/playbooks/.github/workflows/dev-k3s-bootstrap.yml@e4607530b545ccf09e4045113afeb644b067823e`.
The role must not authorize this feature branch; testing a feature dispatch is
blocked until the reviewed control-plane path is on main. The owner contract
specifies the fixed Dev-only read record and in-memory SSH binding. This PR does
not create/change a Vault policy/role, inject GitHub Secrets, or dispatch a run.

## Verification scope

The dedicated offline CI checks out the exact IaC and Playbooks producers and
exercises their actual sanitize -> summarize -> verify -> selected CMDB ->
Playbooks input contract with synthetic runtime objects. It rejects summary or
inventory tampering, plan-as-apply, failed cleanup, multiple targets, missing
runtime identity and matrix mismatch. These are contract tests, not cloud or
business PASS receipts. Runtime provisioning and bootstrap have not run.
