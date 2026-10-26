# Feature lane event gates

Owner: Toolkit control plane. Caller: the existing Control Plane Contracts CI now
falsifies this contract offline. This change does not add a deployment workflow,
new environment, credentials, resource executor, or second dispatch path.

`gate.py` validates a plan at SIT entry and rehearses three event decisions:

1. `sit`: task-linked, genuinely open PR heads target main; full source SHA,
   digest images/chart, config and data baseline; same approved Dev target with
   separate feature SIT/UAT namespaces and temporary domains.
2. `merge`: the current open heads still match, and structured live SIT evidence
   matches the exact candidate, owner workflow/SHA/run, Flux config revision,
   runtime images, data baseline, required tests and human approval evidence.
3. `uat`: all required feature PRs are merged into main with recorded merge SHAs;
   the accepted source artifacts remain unchanged; select the distinct UAT
   namespace/domain on the same Dev target. This is post-merge UAT.

The public `gate()` accepts SIT snapshots only as `PLAN_VALID`, explicitly
unverified. Live merge/UAT always raise BLOCKED because no trusted GitHub/owner
artifact retrieval adapter is connected. Caller JSON, including a field-perfect
receipt or `approved=true`, can never authorize them. `rehearse()` performs
synthetic contract checks and always emits `REHEARSAL`, never live PASS.
Every result keeps `execution=NOT_RUN` and `dispatch_authorized=false`. This is a
library contract, not a deployment controller or a complete live workflow.

## Evidence trust boundary

Candidate data, GitHub snapshots and policy are separate inputs. A future caller
must load policy from its reviewed pinned Toolkit source, resolve PR/run/review
snapshots itself through the existing authenticated GitHub adapter, and download
receipts from the verified owner run. Never let PR code submit its own trusted
snapshots or a caller-provided `approved` boolean. Snapshot validation is not
cryptographic provenance and must not be exposed as a standalone authorization
endpoint. Offline fixtures use invented IDs/domains and do not prove real tests.

Before enabling live dispatch, existing owner integration must additionally:

- verify each image's build manifest and immutable source-SHA provenance;
- verify the retained artifact checksum and exact producer run/attempt;
- retrieve independent human authorization bound to the candidate;
- resolve the approved current Dev IaC/CMDB identity, check the active writer,
  and serialize by feature + target;
- pass the candidate to pinned existing IaC DNS and Playbooks/Flux deployment
  owners, verify actual domain/namespace/database isolation and business probes;
- map merged main commits back to the already accepted PR artifacts without
  rebuilding silently; changed artifact/config/data creates a new candidate;
- independently verify UAT runtime and emit its own receipt.

No live adapter is enabled here: unresolved Dev identity, credentials, owner
workflow or fixed owner SHA is BLOCKED, never a successful no-op.

## Referral scope

Use the original XConnect referral requirement and its remaining acceptance work.
Already merged Accounts #277, Portal #472 and Router #35 are baseline dependencies,
not evidence of premerge SIT. GitOps #602 is a real unmerged configuration repair,
but cannot count as business/Sandbox acceptance. Accounts #278's mock support is
not automatically selected as a business candidate. A real remaining repair PR
must be linked to the requirement; no empty PR or invented functionality is
needed to demonstrate an open PR. Required referral tests must retain real Stripe
Sandbox, DDL refusal, rootless and immutable image/Flux evidence; mock passes do
not meet those requirements.

## Verification

Run `python3 scripts/tests/control_plane/feature_lane_gate_test.py -v`.
Negative cases reject merged-baseline-as-SIT, changed heads, forks, mutable or
missing artifacts/baselines, namespace/domain drift, wrong producer run, mock or
incomplete receipts, changed configuration, missing human authority and premerge
UAT. No cloud, host, database, Stripe or Vault access is performed.
