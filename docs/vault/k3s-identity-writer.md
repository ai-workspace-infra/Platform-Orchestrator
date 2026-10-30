# Master-generated Kubernetes credential writer

This change declares the issuance-only role
`github-actions-platform-ops-toolkit-prod-k3s-v6-identity-writer`.
Its only policy grants create/read on the three role-specific credential records.
It grants no update/delete/list, adjacent-path, metadata, SSH, cloud, CA-key or
Vault administrative access. No default policy is inherited. The batch token
expires within 10 minutes; reauthentication is required for retry after expiry.

The owner is the Vault identity administrator. The intended caller is the
protected production selfhost workflow at a reviewed v6 tag. The credential
issuer/archiver is the master-side Playbooks implementation in
[Playbooks #886](https://github.com/ai-workspace-infra/playbooks/pull/886).
This PR declares the role/policy; it does not wire a new workflow action, dispatch
an operation, or apply Vault configuration. The caller must explicitly select
this role and call the reviewed immutable Playbooks entrypoint before it can be
used. Existing bootstrap roles are not widened.

After review and merge, an authenticated Vault administrator can apply only this
declared role/policy with the existing provisioner:

```bash
bash scripts/create_vault_service_repo_roles.sh --apply \
  --role github-actions-platform-ops-toolkit-prod-k3s-v6-identity-writer
```

The runtime writer must receive no other policy. Do not hand a Vault root/admin
token to the master. The controller authenticates via the allowed GitHub OIDC
route and passes only the short-lived scoped credential to the Playbooks owner.
The client CA private key remains on the master; only per-role leaf credentials
are archived. Initial issuance uses CAS=0; existing records must not be silently
replaced, even if a concurrent writer wins. Rotation requires a separately
reviewed contract and is not granted here.

Static contract tests validate exact paths/capabilities, policy isolation, TTL,
and repository/environment/ref/workflow bindings. They are not live authorization
acceptance. Before target use, verify actual OIDC authentication from the allowed
workflow and rejection for wrong repository, environment, ref and workflow.
Verify target record read/create during real initialization, adjacent-role-name,
other-cluster/environment and update/delete/list denial without printing secrets.
Do not write dummy values into production credential destinations to test access.
Capture redacted audit actor/role/path/request ID and Playbooks receipt.

Rollback: remove this dedicated role/policy through the existing reviewed admin
process; stop its caller and wait for issued batch tokens to expire. Removing a
role/policy or Vault record does not revoke already issued Kubernetes client
certificates. Preserve master issuance state and administrator recovery access.
