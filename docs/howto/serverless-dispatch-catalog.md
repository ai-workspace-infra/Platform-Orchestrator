# Serverless dispatch catalog

Source: `.github/workflows/serverless-orchestrator.yml` and its five local stages plus four deployment phase workflows.

Track: [#1445](https://github.com/ai-workspace-infra/platform-ops-toolkit/issues/1445).

| Input | Type | Required | Default | Execution contract |
| --- | --- | --- | --- | --- |
| `operation` | choice | true | `deploy` | plan validates; deploy/upgrade deploy; schema/import/destroy operations retain their existing explicit gates. |
| `target_domains` | choice | false | `all` | Consumed by the existing input validator and/or selected owner calls. |
| `cloud_provider` | choice | false | `gcp-cloud` | Consumed by the existing input validator and/or selected owner calls. |
| `vault_env_path` | choice | false | `uat` | Explicit environment; this validation is UAT only. PROD requires existing release and promotion authorization. |
| `tag_ref` | string | false | `(empty)` | Consumed by the existing input validator and/or selected owner calls. |
| `website_content_ref` | string | false | `main` | Current default main is mutable; resolve a reviewed commit for a reproducible validation. |
| `accounts_schema_ref` | string | false | `main` | Compatibility only: init-schema is retired and fails; this ref is not consumed. |
| `apply_accounts_schema_migration` | boolean | false | `false` | UAT only; requires increasing expected/target versions and exact SHA-256; preserves checkpoint-before-migration. |
| `adopt_accounts_baseline` | boolean | false | `false` | UAT deploy + Cloud Run only; incompatible with other schema requests. |
| `accounts_schema_expected_version` | string | false | `(empty)` | Consumed by the existing input validator and/or selected owner calls. |
| `accounts_schema_target_version` | string | false | `(empty)` | Consumed by the existing input validator and/or selected owner calls. |
| `accounts_schema_sha256` | string | false | `(empty)` | Consumed by the existing input validator and/or selected owner calls. |
| `probe_accounts_schema` | boolean | false | `false` | Read-only UAT plan only; incompatible with apply/baseline. |
| `deploy_cloudflare` | boolean | false | `true` | Consumed by the existing input validator and/or selected owner calls. |
| `deploy_cloud_run` | boolean | false | `true` | Consumed by the existing input validator and/or selected owner calls. |
| `cloud_run_service` | choice | false | `(empty)` | Empty selects all three services; partial matrices do not prove a full release. |
| `skip_stripe_catalog` | boolean | false | `false` | true disables optional catalog reconciliation. |
| `dns_mode` | choice | false | `none` | none keeps canonical aliases unchanged; domain owner may still reconcile mode-qualified service domains. Cutovers require separate explicit approval. |
| `accounts_source_backend` | choice | false | `supabase` | Compatibility only: not consumed; legacy import remains explicitly disabled. |
| `supabase_source_tunnel_host` | string | false | `console.svc.plus` | Compatibility only: not consumed; no source-host import is enabled. |
| `supabase_target_existing_strategy` | choice | false | `accounts_merge` | Compatibility only: not consumed by the unified data dispatch. |
| `supabase_target_confirm_replace` | boolean | false | `false` | Retired and ignored; never enables replacement. |
| `runner_type` | string | false | `ubuntu-latest` | Compatibility only: not consumed; jobs keep their existing ubuntu-latest runners. |
| `promotion_manifest` | string | false | `(empty)` | Required by existing PROD promotion validation; not used for this UAT validation. |

## UAT deployment verification preflight

- Select a reviewed control revision whose stage claims are live for UAT. Never broaden the ref allowlist to run a feature branch.
- Verify the GitOps SHA, UAT resource manifest and target set. Reject production projects, V5/K3s targets, DNS cutovers, destroy and imports.
- Resolve and verify the immutable application snapshot and all selected artifacts/builds before mutation. Reuse published artifacts; do not create or move tags for this check.
- Use `operation=deploy`, `target_domains=web-saas`, `cloud_provider=gcp-cloud`, `vault_env_path=uat`, `dns_mode=none`, no schema requests, no import, and `skip_stripe_catalog=true`.
- Check checkpoint routing stays on the serverless UAT database owner. A checkpoint is an existing prerequisite, not authorization for a data merge or restore.
- State every resolved input before dispatch. Follow the exact run and independently verify the selected service endpoints and receipts. Record failures without claiming live acceptance.
- This UAT scope never dispatches Selfhost, Hybrid, the Daily Snapshot deployment fan-out, or the K3s orchestrator. PROD declarations may be reviewed in Git; no PROD role/configuration is applied during UAT verification.

The current caller graph, owner SHA pins and public service probes are preserved by the refactor. See the matrix runbook for the five-phase DAG and authorization rollout dependency.
