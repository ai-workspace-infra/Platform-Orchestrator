# V5 Console brand route receipt

The approved brand hostname cutover was completed on 2026-10-24 (Asia/Shanghai). The Toolkit route now resolves the generation resource, account, workspace and existing state from the reviewed GitOps Akamai target. Terraform state was read to regenerate the exact single-host CMDB; no infrastructure apply was run.

## Fixed execution sources

- Toolkit: `8b9bc4bf12694b7e5a1c959ba168d86f094abd3d`, release `v2026.10.24-r1`, PR #1432.
- GitOps execution input: `040502287d904a8847edb58008f1fc2959cdc730`.
- IaC owner: `f889d68cb91434f7d18a72731e496d5e71a6f571`.
- Final Playbooks owner: `5f406807fb33a3c9a44fbc44c6c26eced7ee41a3`, Playbooks PRs #749 and #751.
- Run: `v5-brand-20261024T143751`; start `2026-10-24T14:37:51.905035+08:00`; end `2026-10-24T14:38:24.937845+08:00`.

## Observed outcome

- Only an isolated brand Caddy block was appended. The original Caddy configuration bytes match the pre-change SHA256 after removing that block.
- The restored public certificate covers the brand hostname and expires on 2027-01-05. No ACME issuance was used.
- Only Caddy was restarted, with explicit operator authorization. Existing domain response statuses and all other container identities/start times remained unchanged.
- Three subsequent runs of the frozen final Playbooks owner each reported `changed=0`, `failed=0`; no additional Caddy restart occurred.
- The single apex A record was changed through the pinned IaC DNS owner. The previous provider record was checkpointed before the write. Provider readback, public DNS resolvers and HTTPS returned the V5 target / HTTP 200.
- Console, Accounts and Billing CNAMEs retained their V5 targets. PostgreSQL was observed pointing to its pre-existing V2 target and was preserved as explicitly requested; it was not silently migrated.

## Preserved failure and recovery history

The initial isolated deployment succeeded. Its first repeat was rejected by an OpenSSL check that combined hostname and expiry operations; OpenSSL returned only the expiry result. That repeat did not restart Caddy. PR #751 separated both checks, required an explicit hostname match, and skipped unchanged PEM restoration. The three accepted zero-change runs above used the frozen merged owner; the earlier mixed-checkout repeat is not acceptance evidence.

No database migration, backup restore, credential rotation or business-account acceptance was run (`NOT_RUN`). Raw CMDB, private runtime inputs, DNS checkpoint and complete local receipts remain in controlled operator storage. Temporary scoped deployment tokens were revoked; private runtime variable files were removed.
