# Existing migration dispatch route: integration preflight

Task: codex://threads/01a1691f-61fc-7843-9e1d-e04d1bfe900d.
Inspection and real SSH/Role validation: 2026-10-25. No new or modified workflow.

The existing `selfhost-orchestrator.yml` dispatches `selfhost-stage-verify.yml`
after migrate. That child already has `observe_web_saas_after_dns` host matrix,
so adding another acceptance workflow is unnecessary. The existing matrix
calls Playbooks `verify_web_saas_post_deploy.yml`, not the new
`v5-readonly-acceptance.yml`. Its current SSH setup disables host-key checking,
and its gate requires `migration_context.switch_dns.result == success`.

The terminal `verify` branch of `stage-dispatch.py::download_context` currently
returns only run ID/attempt/URL and trusts workflow conclusion. Its existing
contract test explicitly verifies that no context artifact is downloaded. This
is current behavior, not evidence that the new strict receipt gate is active.

The other existing `web-saas-k3s-orchestrator.yml` selects UAT and includes
provisioning, DNS updates and bootstrap. It is not a safe production acceptance-
only route for the current V5 host. Do not dispatch `full` merely to test a role.

## Current disposition

Dispatch: preflight_failed / NOT_RUN. The role is under draft PR review,
independent UAT owner→caller receipt evidence is absent, and there is no exact
current migration-parent run/attempt/CMDB context authorized for a production
read-only replay. Do not manufacture parent contexts, substitute UAT for PROD,
run a migration or DNS switch again, disable SSH identity checking, or accept
workflow success as the final receipt.

A subsequent focused change can reuse the existing verify host matrix after
owner review and UAT. It must consume immutable Playbooks SHA and exact
migration parent/run/attempt/host context; bind expected environment/namespace
and independently trusted host keys; call the same tested Role; upload
sanitized failed/successful results even when assertions fail; and validate
exact artifact provenance plus the complete required check set before the
parent releases. Missing, invalid, skipped or mismatched evidence blocks.
This audit does not enable that route or delete legacy implementations.

## Evidence distinction

Real strict-SSH tests executed the Playbook/Role on the cloud-verified existing
V5 K3s instance. Four effectiveness cases passed: baseline evidence-before-
block, wrong machine identity, wrong environment and wrong GitOps SHA. They
prove the tested Role's rejection behavior; business acceptance remains FAIL
and the migration dispatch route remains NOT_RUN. Temporary manual inventory
was scoped to that run and removed afterward; no authority CMDB was fabricated.

Existing dispatch contract tests (7) and strict receipt tests (55) passed
locally; no operational Actions dispatch was performed. The runtime
`v5-readonly-observation/v1` result is not a GitHub dispatch receipt and cannot
be used to claim completion of V5-23.

## Later scoped integration

The user selected `environment-data-operations.yml` as the single integration
point instead of the Selfhost stage chain. See `v5-environment-data-matrix.md`: one
optional existing-workflow matrix now calls the same owner Role and validates
automatically generated reports. The Selfhost findings above remain historical
audit evidence; its workflows and stage dispatcher were not changed. Actual
Actions execution and UAT qualification remain NOT_RUN.
