# Feature SIT data baseline evidence

A schema-v2 Feature candidate freezes `data_baseline_sha256` before deployment.
The digest identifies a reviewed, immutable non-production baseline input, not
an assertion that a database or namespace already exists. Its producer must be
a reviewed Main workflow with a fixed commit, and must verify the provenance and
content of the baseline input before publishing `sit-data-baseline/v1` evidence.
The evidence records the Feature ID, its intended namespace, the input digest,
and `result: verified`; it must never contain database credentials or data.
The reviewed workflow policy selects the owner repository, workflow, commit,
event, artifact name and document path; callers provide only run, attempt and
artifact IDs. The feature gate independently retrieves the artifact and binds
its digest and intended namespace to the candidate. A copied caller assertion
or a syntactically valid digest alone is not baseline evidence.

The intended namespace is a name in this pre-deployment contract, not proof of
a live namespace or its UID. After a candidate is accepted, a separate owner
must establish or independently observe the actual isolated data state and
produce a receipt binding the candidate, current namespace UID and the verified
baseline. Runtime and business acceptance remain NOT_RUN until that receipt,
actual service health and integration checks pass. Never use a pre-deployment
baseline document as an initialization or readiness receipt.

Issue #1483 does not authorize database initialization, migration or reuse of
another lane's data. A missing approved baseline or actual data-state receipt
blocks the relevant stage; this contract does not provide either or authorize
new database operations. The baseline producer, its least-privilege identity,
actual evidence and the database owner remain separate implementation work.
