---
name: multi-environment-delivery-and-release
description: Use when changing platform-ops-toolkit delivery workflows, job matrices, stage dependencies, environment routing, Vault OIDC or release paths. Enforces compact pipeline graphs, owner handoffs and environment isolation.
---

# Multi-Environment Delivery and Release Standard

When changing delivery in `platform-ops-toolkit`, follow repository AGENTS.md and the checked-in workflow, referenced scripts/actions and GitOps contracts. Resolve conflicts with historical prose against current source before execution; documentation alone does not authorize a dispatch or environment mutation.

## 1. Environment Routing Rules

The workflow `selfhost-orchestrator.yml` routes selfhost infrastructure traffic to specific environments based on Git events. Never hardcode environments outside of these bounds:
- **`pull_request`** -> routes to **`sit`** environment (`sit/all-in-one.yaml`).
- **`main` or `release/*` push** -> routes to **`uat`** environment (`uat/web-saas-uat.yaml`).
- **`vMAJOR.MINOR.PATCH` tag** -> routes to **`prod`** environment (`prod/web-saas-prod.yaml`).

## 2. Vault Authentication & Secrets
- **DO NOT** store sensitive credentials in GitHub Actions Secrets.
- Authentication must use GitHub OIDC → Vault JWT.
- Environments are strictly isolated. Ensure you select the correct Vault role (`github-actions-platform-ops-toolkit-sit`, `-uat`, or `-prod`) depending on the context.

## 3. Branching Lifecycle
- Always use Pull Requests. **Do not push directly to `main` or `release/*`**.
- `feature/*` and `bugfix/*` MUST target `main`.
- `hotfix/*` MUST target `release/*`.
- Production deployments ONLY occur via annotated tags (`v*`).

## 4. Emergency Secret Leaks
If a secret is exposed in the repository:
1. **Revoke** immediately in Vault/Provider.
2. **Generate** a new credential.
3. Purge the Git history (e.g. using `git filter-repo`)—do not merely "delete" the file in a new commit.

## 5. Legacy Workflow and Matrix Cleanup
- A job explicitly marked `legacy`, `deprecated`, or `disabled` is not an accepted long-term compatibility layer. Remove it from the workflow once the replacement entry point is active; do not keep a dead matrix as a guarded job.
- Removing a legacy matrix is a complete dependency-graph change: remove the job, every `needs` reference, job outputs, summary environment/result fields, dead `if` branches, and dispatch scripts that have no remaining caller.
- Update or delete contract tests that assert the retired path. Verify the repository has no remaining references to the retired job, matrix outputs, dispatcher, or legacy guard.
- Preserve active provider and namespace routing. A retired aggregate matrix must not be confused with a still-used single-namespace route or the current Hybrid Orchestrator.
- Before merging, run shell syntax checks, the affected routing/dispatch contract tests, YAML parsing, and a `needs`-graph check so no active job points to a deleted dependency.


## 6. Pipeline Graph: At Most Five Sequential Stages

- Every workflow, including reusable and dispatched child workflows, MUST have a longest static `needs` path of at most **5 jobs**. Prefer **3–5 stages** for delivery orchestrators; simple CI may use fewer. Matrix replicas and parallel jobs at the same dependency depth do not add stages. Renaming jobs to `[1/5]` does not shorten the DAG.
- Before editing, count actual depth and identify each job's outputs, permissions, Environment approval, failure conditions and callers. After editing, report the before/after depth and verify no missing dependency or cycle remains.
- Merge sequential control checks into steps when they share runner, permission and approval boundaries. Use job matrices for independent organizations/providers/targets. Do not serialize independent work or parallelize tasks that consume an upstream receipt.
- Keep independent runner or approval boundaries in owner workflows. A parent may dispatch a bounded stage workflow, wait for its exact run, validate its receipt and publish outputs. Child graphs must also meet the five-stage rule; moving a long chain into a child only hides debt.
- Preserve Toolkit control ownership: IaC operations dispatch the approved IaC entry; data operations dispatch `environment-data-operations.yml`; host/application execution stays in pinned Playbooks owners; GitOps declares topology and capabilities. Graph compression must not copy execution commands into Toolkit.

Daily Snapshot example: `Prepare → Build (organization matrix) → Gate → Deploy (environment matrix) → Summary`. Gate runs completed-tag validation, pinned Shared read-only readiness and environment selection in order. A selected-repository build intentionally skips Gate/Deploy; a full snapshot does not.

### Failure and Dispatch Contracts

- A failed, cancelled or unexpectedly skipped prerequisite MUST block mutation. A successful dispatch is not a successful child execution. Keep bounded polling, exact parent/child run correlation, environment/ref identity and artifact/checksum evidence; never select an unrelated latest run.
- Terminal reporting may run with `always()`, but MUST fail on unsuccessful required stages or missing/invalid evidence. Distinguish explicitly unselected work from unexpected skips. Removing checks, approval gates or error propagation to shorten the graph is prohibited.
- Declare timeout and retry bounds for child dispatch/wait. Retry transient failures only within those bounds; an identical failure without new evidence must stop automatic retries and produce the failing run URL, cause and next prerequisite. Never loop by redispatching unchanged inputs or widening credentials/permissions.
- A docs/code change, PR merge or offline check is not runtime acceptance and does not authorize PROD execution. Record SIT/UAT runtime evidence separately by immutable version and target.

### CI Enforcement and Existing Debt

Use the repository-owned policy rather than maintaining another workflow list here:

- [Stage-depth policy](../../scripts/ci/workflow-stage-depth-policy.json): maximum 5; existing exceptions are frozen debt ceilings, not completed refactors. Do not add exceptions or raise ceilings to make CI pass. Lower ceilings after shortening a legacy chain and remove an exception at 5 or fewer.
- [Graph checker](../../scripts/ci/workflow_stage_depth_verify.py) and [contract tests](../../scripts/ci/tests/test_workflow_stage_depth.py) run in Repository Conventions. Run them locally with affected routing/gating checks before submitting the PR:

```bash
python3 scripts/ci/workflow_stage_depth_verify.py
python3 scripts/ci/tests/test_workflow_stage_depth.py -v
python3 scripts/ci/workflow_gating_verify.py
```

Update the [refactor record](../../docs/iac/workflow-orchestrator-refactor-2026-10-12.zh.md) when changing graph shape, documenting retained execution/approval boundaries, deliberate skips, remaining debt and the exact validation scope.
