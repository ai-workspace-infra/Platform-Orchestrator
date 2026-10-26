# Feature lane event gates

Owner: Toolkit control plane. Caller: the existing Control Plane Contracts CI now
falsifies this contract offline. This change does not add a deployment workflow,
new environment, credentials, resource executor, or second dispatch path.

`gate.py` validates a plan at SIT entry and rehearses three event decisions:

1. `sit`: task-linked, genuinely open PR heads target main; full source SHA,
   digest images/chart, config and data baseline; same approved Dev target with
   a temporary feature SIT namespace/domain and the independently declared stable
   UAT namespace/host from trusted policy. Both pairs must differ.
2. `merge`: the current open heads still match, and structured live SIT evidence
   matches the exact candidate, owner workflow/SHA/run, Flux config revision,
   runtime images, data baseline, required tests and human approval evidence.
3. `uat`: all required feature PRs are merged into main with recorded merge SHAs;
   an explicit merge-SHA-to-artifact mapping binds the merge SHA, accepted PR head,
   image digest, manifest checksum and equal source/merge tree SHAs. A changed
   merged tree or artifact requires a new candidate and re-testing; API merge
   status alone is insufficient. Select the trusted stable UAT namespace/host on
   the same Dev target. This is post-merge UAT.

The public `gate(candidate, stage="merge", policy_commit=<full SHA>, evidence_selectors=selectors)` retrieves
trusted evidence. It rejects simultaneous caller policy/PR/receipt/run/approval
objects. A successful check emits `VERIFIED_GATE`, `execution=NOT_RUN` and
`dispatch_authorized=false`; it neither merges nor dispatches. The legacy raw
snapshot path remains unverified for SIT and BLOCKED for merge/UAT. `rehearse()`
always emits `REHEARSAL` and cannot authenticate evidence.

## Trusted policy and authenticated retrieval

The repository is fixed to `ai-workspace-infra/platform-ops-toolkit` and policy
path to `.github/policies/feature-lane.json`. An explicit full commit must be on
current main ancestry, and its policy blob must equal the current-main policy
blob. This uses the repository's normal main governance; it adds no independent
review/approval ceremony. A feature PR cannot substitute local policy JSON,
change the policy repository/path, or select a superseded policy. No active
policy is created by this PR. A missing policy is BLOCKED.

Policy supplies only stable allowlists and execution identities: approved Dev
and stable UAT targets, SIT domain suffix, task/source repositories, required tests,
`build_owners`/`merge_build_owners` workflow/event/filename/artifact-prefix identities,
and the reviewed acceptance-owner code SHA. It does **not** contain a feature task,
PR head, run/artifact/attempt IDs or authorization comment ID.

The caller may provide an untrusted candidate task URL and `evidence_selectors`:
`builds` and (for UAT) `merge_builds` map each participating repository to exactly
`{run_id, attempt, artifact_id}` positive integers; `acceptance` has the same three
IDs; `authorization` contains exactly `{issue, comment_id}` positive integers. The
authorization repository comes from the allowed source in policy; it may differ
from the task-file repository. No selector may override a
repository, workflow, event, filename, source SHA, environment or approving user.
The adapter derives service SHA from the candidate/current PR API, merge SHA from
the merged PR API, and artifact name from the policy prefix plus run and attempt.
The task may be a real Issue in an allowed repository, or a fixed-40-SHA
`/blob/<sha>/<path>` file URL with `task_sha256`. File roots are controlled by
stable `task_paths` policy; authenticated contents API verifies repository, path,
commit and SHA256. Mutable branch URLs are refused. A source PR links the selected
authority; a repository with Issues disabled need not invent an Issue.
Thus a second task/head/run candidate uses the same policy blob without merging
runtime facts to main. Missing/extra selectors or foreign task/source are BLOCKED.

The adapter fetches authenticated GitHub
API metadata through the existing migration-matrix artifact reader. It validates
owner workflow/event/SHA/repository, successful run and exact attempt, rejects
fork producers and expired/mixed-run artifacts, and verifies GitHub's archive
SHA256 before reading the expected document. Both actual download and expanded
ZIP contents have size/count limits; traversal, symlinks, encryption and duplicate
receipt entries are rejected without extracting an archive. The merge mapping's
manifest checksum is computed from retrieved bytes, not trusted as a payload
claim. Producer source/image manifests and current PR heads must match.

`authorization` is an optional configured evidence-source contract, not a new
universal approval policy. The implemented `kind: issue_comment` source permits
allowlisted human authors; the approval issue/comment IDs are untrusted selectors in its policy-selected
repository, resolved and checked through current API data. The task need not be
that Issue: the approval binds the entire candidate fingerprint, including its
immutable task source. Current
API data must show a User with OWNER/MEMBER/COLLABORATOR association, the correct
issue and canonical comment URL, unchanged created/updated timestamps, and exact
body `APPROVE feature-candidate <candidate_sha256> action=merge` (or `action=uat`).
A deleted/edited comment or subsequent same-author REVOKE/REJECT for the candidate
blocks the decision. Comments remain mutable and deletable; this is a current
retrieval check, not a signature or immutable approval. No configured supported
source means BLOCKED; this adapter does not invalidate authorization already
given in chat or manufacture a substitute GitHub record.

The repository policy has no real owner receipt/run configured in this branch.
A real read-only policy probe is BLOCKED because the active policy file is
unavailable. Tests use explicitly synthetic API/ZIP fixtures and never count as
live referral/Sandbox acceptance.

## Configuration changes and independent runtime components

A real unmerged application-image PR is not mandatory when the selected change is
configuration-only. `configurations` is a separate member list: repository, PR,
full head/base SHA, base ref and a bounded path-to-SHA256 map. Policy
`configuration_paths` limits readable roots. The adapter fetches the actual PR and
contents at the fixed head and verifies all hashes; no image is invented for a
GitOps PR. A stacked configuration member explicitly selects its main-target
parent PR/head and one configuration_entrypoint; only that selected change needs
the direct authority link, while its parent is a fixed verified dependency. Such a stack may enter SIT, but cannot directly claim main/UAT:
the accepted paths must be verified on an actual merged-main configuration.

Configuration candidates require `components`, independent of PR membership.
Stable policy `runtime_components` fixes the complete component-to-source mapping;
each component's digest must match a verified image source, and the receipt's
imageID map must match exactly. Accounts/console/PostgreSQL cannot be dropped or
replaced just because their source PRs are already merged. Existing build
provenance and acceptance checks remain in place.

`fixtures/xconnect-referral-declarations.json` records the real authority task-file
hash, original merged baseline SHAs, #599/#602 current heads/bases and configuration
path hashes. It is a declaration snapshot, not a live candidate or acceptance.
PostgreSQL producer SHA/build evidence, isolated data baseline, approved target
policy and real owner receipts remain explicitly missing. The external Router
Worker is not an in-lane container and remains NOT_RUN for routed-flow acceptance.
Tests prove a configuration PR with merged image baselines is expressible; they do
not retrofit premerge SIT onto historical Accounts #277/Portal #472/Router #35.

## Remaining live owner integration

The adapter verifies evidence and returns a decision only. Existing owners still
must create the reviewed declaration/policy, build manifests and real SIT receipt,
resolve the current Dev IaC/CMDB identity, check the active writer, and serialize
by feature + target. Then the reviewed existing IaC DNS and Playbooks/Flux owners
must perform the resource operations and emit real probes. No cloud, host, state,
SSH, database, DNS, Vault or Stripe operation is implemented here.

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

Run `python3 scripts/tests/control_plane/feature_lane_gate_test.py -v` and
`python3 scripts/tests/control_plane/feature_lane_trusted_test.py -v`.
Twenty-two gate groups and twenty-one adapter groups include a valid attempt-3 rerun and reject mismatched attempts,
null/unknown baseline fields, undeclared UAT targets, missing/changed merge-artifact
mappings, merged-baseline-as-SIT, changed heads, forks, mutable or
missing artifacts/baselines, namespace/domain drift, wrong producer run, mock or
incomplete receipts, changed configuration, missing human authority and premerge
UAT. No cloud, host, database, Stripe or Vault access is performed.
