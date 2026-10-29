# Feature SIT evidence identity

The platform delivery team owns this identity. The sole consumer is the
`feature-tag-trusted-main.yml` evidence job, running on reviewed Main in the
existing `dev` GitHub environment for the Dev-hosted SIT lane. It cannot deploy.

Provision a dedicated GitHub App installed on the selected repositories in
`ai-workspace-infra` and `ai-workspace-services`, with only Actions, Contents,
Issues and Pull requests read permissions. Store its app ID and private key as
`app_id` and `app_private_key` in `kv/sit/platform/github-app/feature-lane`;
never copy the daily snapshot App key. The reviewed candidate and policy bound
the repositories in each short-lived installation token.

The declared Vault role reads only that exact KV v2 data path, is bound to the
repository ID, owner ID, Main workflow/ref and Dev environment, and has a
maximum 10-minute batch-token lifetime. Rotate the App key at least every 90
days; revoke it at GitHub and replace the Vault value if compromised. Audit
the Vault login and read and the GitHub App token issuance without recording
key or token material.

The App, Vault secret and role are not yet provisioned or tested. Before use,
apply the reviewed role and policy through the Vault owner and verify that the
intended workload can read the one path, while another ref, workflow,
environment and adjacent secret paths are denied. A missing identity must fail
the evidence gate; it cannot authorize DNS, deployment, merge or acceptance.
