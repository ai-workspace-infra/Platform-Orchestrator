# Accounts main → Dev UAT release proposal

Owner: Toolkit control plane. App build/publish remains Accounts; GitOps remains
the desired-state owner; Flux deploys only merged GitOps main. This is a narrow
Accounts-first writer, not another deployment controller or a generic release
platform. It preserves the other five components in the complete web-saas matrix.

## Exact chain and dependencies

1. Accounts #279 adds `main-image-build.json` to the existing successful GHCR
   main-push publication. It derives the digest from the actual SHA-tag push
   transcript, not a workflow input or mutable tag. The artifact is named
   `accounts-main-image-<run>-<attempt>` and binds source_repository/source_sha,
   event/ref/run/attempt/platform and `image@sha256`. Existing snapshot
   release-manifest.json lacks an OCI digest and is deliberately not accepted.
2. Land Toolkit #1454 first. `uat_release.py` imports its `trusted.artifact` /
   shared bounded authenticated `migration_matrix.reader.api`; missing that
   dependency blocks. No copied artifact verifier, caller evidence JSON, third
   authentication path or new Vault privilege is introduced.
3. The reviewed GitOps full-stack declaration must supply exactly
   `services/distributed-web-saas-fullstack/dev/uat/release.yaml` on protected
   main. Only that path is changed. Six component source repositories are
   allowlisted in code; their fixed image references and source/run/digest
   annotations are checked. Accounts/billing/content runtime `env.IMAGE` must
   match workload image. Existing five component sources/digests are preserved,
   not retroactively re-certified by this Accounts update.
4. The trusted caller supplies only current GitOps base SHA and positive
   Accounts run/attempt/artifact selectors. The writer independently retrieves
   current Accounts main, run ownership/path/status/event/ref and the artifact,
   requiring a successful push/main build of the **current** main SHA, from the
   Accounts head repository. Tags, forks, failed runs, dispatch and stale selectors
   fail closed. It rechecks both mains after retrieval and before publication.
5. A complete six-component matrix fingerprint is computed from canonical
   release values and recorded in the output header/proposal metadata. This
   matrix hash is not the full feature candidate (chart/config/data and runtime
   acceptance remain separate). A local patch is the default. Explicit
   `--open-pr` constructs one-file Git objects, a new `feature/dev-uat-accounts-*`
   branch and a **draft PR** to protected GitOps main, using existing gh CLI
   authentication. It never updates main, auto-merges, dispatches deployment,
   changes DNS/state, reads Vault or requests a new credential. Publication
   re-fetches the authenticated evidence; a fabricated local plan cannot be used.
6. Parent owns actual mutation. No CLI publication, app main build or UAT
   runtime execution has been performed by this implementation. After review /
   checks and existing merge authorization, Flux main watch consumes the merged
   values. A newer app main or changed GitOps base requires selecting again,
   not transplanting stale proof. A branch left by an interrupted PR operation
   is retained for inspection; no force/update/delete cleanup is attempted.

Example (selectors must come from the real successful new producer run):

```sh
python3 .github/scripts/feature-lane/uat_release.py \
  --gitops-base FULL_CURRENT_GITOPS_MAIN_SHA \
  --run-id RUN_ID --attempt ATTEMPT --artifact-id ARTIFACT_ID \
  --output /absolute/path/dev-uat-release.patch
# Parent may run the same authenticated selection with --open-pr when authorized.
```

This first hook is an explicit controller invocation after build, not an
unauthenticated repository_dispatch listener. It requires existing cross-repo
gh read/write permissions for the caller; absent access blocks and is not fixed
by copying a token or changing Vault. Automatic event dispatch can later call
the same selector-only entrypoint under the existing trusted control plane;
there is no wildcard caller acceptance.

## Observed gap and runtime status

Accounts successful main run `40211794719` at source
`8d1b09a6f2022af221b2a817d516952af41ced0e` contains only a dockerbuild record,
not the required small digest artifact. Snapshot tag run `40222728214` publishes
release-manifest.json with commit/SHA tag but no OCI digest. The tag run's
separate logged digest was useful provenance investigation, not accepted machine
proof for this writer. Therefore the new chain remains **BLOCKED** until the
producer change is reviewed/merged, a genuine successful main build publishes
its artifact, #1454 lands, and the UAT release declaration is merged. Nothing in
unit fixtures or this controller PR demonstrates actual UAT deployment/business
acceptance. SIT PR-candidate artifacts remain governed by their existing safe
publication route and are not relabeled as main proof.
