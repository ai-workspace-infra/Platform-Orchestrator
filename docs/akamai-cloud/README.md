# Akamai Cloud/Linode Vault KV

本目录是 Akamai Cloud/Linode IAC 初始化的操作入口。Terraform 使用官方
`linode/linode` provider，凭据字段统一使用 `LINODE_TOKEN`；不使用
`AKAMAI_API`。

## 文件

- [`bootstrap-vault-kv-tldr.md`](bootstrap-vault-kv-tldr.md)：路径、字段和最短执行步骤。
- [`uat-prod-bootstrap-runbook.md`](uat-prod-bootstrap-runbook.md)：UAT/PROD Role、KV、workflow 与故障修复流程。
- [`uat-six-namespace-migration-plan.md`](uat-six-namespace-migration-plan.md)：面向人类和代码代理的 UAT 六 namespace、阶段 A-E、迁移门禁与仓库/Project/PR 关联规范。
- [UAT migration preflight](../howto/akamai-uat-migration-preflight.md)：只读核对 legacy state、六个 namespace、Linode 资源和后续 state retirement 门槛。
- [`init-vault-kv.sh`](init-vault-kv.sh)：初始化 state KV，并调用仓库中已有的 Akamai token/OIDC bootstrap。
- `scripts/cloud/bootstrap/Akamai-Cloud/bootstrap_akamai_cloud_kv.sh`：只写入 Akamai provider token。
- `scripts/cloud/bootstrap/Akamai-Cloud/bootstrap_akamai_oidc_roles.sh`：创建环境/账户绑定的 Vault JWT role 和 read-only policy。

`scripts/cloud/bootstrap/Akamai-Cloud/` 是唯一入口；旧的 `scripts/vault/bootstrap_akamai_*.sh`
兼容包装器已移除。

## 路径契约

```text
kv/CICD/<env>/akamai-cloud/<account>
  LINODE_TOKEN

kv/CICD/<env>/iac_state
  TF_STATE_ENDPOINT
  TF_STATE_BUCKET
  TF_STATE_ACCESS_KEY
  TF_STATE_SECRET_KEY
  TF_STATE_REGION
```

`<account>` 必须是真实 Akamai Cloud/Linode 账户名或 ID。`primary`、`default`、
`main` 等别名会被拒绝。`VAULT_TOKEN`、`AKAMAI_ACCOUNT_*` 是初始化时的运行时
输入，不写入 KV。

## 执行

```bash
export VAULT_ADDR='https://vault.svc.plus'
export VAULT_TOKEN='hvs.***'
export LINODE_TOKEN='***'
export AKAMAI_ACCOUNT_UAT='<真实账户名或ID>'
export AKAMAI_ACCOUNT_PROD='<真实账户名或ID>'
export TF_STATE_ENDPOINT='https://s3.example.com'
export TF_STATE_BUCKET='terraform-state'
export TF_STATE_ACCESS_KEY='***'
export TF_STATE_SECRET_KEY='***'
export TF_STATE_REGION='us-east-1'

bash docs/akamai-cloud/init-vault-kv.sh --apply --env all
bash docs/akamai-cloud/init-vault-kv.sh --check --env all
```

完成 KV 初始化后，按环境执行 `plan` / `apply` 的 workflow 参数和验证步骤，见
[`uat-prod-bootstrap-runbook.md`](uat-prod-bootstrap-runbook.md)。

如果 UAT/PROD 共用同一个实际账户，两个 `AKAMAI_ACCOUNT_*` 可以相同；Vault
路径和 GitHub OIDC role 仍按环境分开。

## 安全边界

- token 不写 GitHub Secrets、Git、Terraform 配置、plan artifact 或日志。
- `LINODE_TOKEN` 只用于 `linode/linode` provider。
- state 凭据只从 `kv/CICD/<env>/iac_state` 注入 workflow。
- state key 由 environment/project/cloud/account/workspace 五级参数生成。
- 当前 workflow 仍需要 `TF_STATE_ACCESS_KEY` 和 `TF_STATE_SECRET_KEY`；切换到 AWS OIDC → STS 后，需同步移除对应 KV 字段读取和 policy 权限。

### Dev identity template (review before apply)

`bootstrap_akamai_oidc_roles.sh --env dev` is an explicit opt-in using
`AKAMAI_ACCOUNT_DEV`; `--env all` continues to mean UAT + PROD. The Dev role
uses exact string claims for this repository, `refs/heads/main`, environment
`dev`, caller `dev-host-lifecycle.yml@refs/heads/main`, and reusable job
`iac-pipeline-multi-cloud-stages.yaml@refs/heads/main`. The caller follows the
reviewed #1453 chain: lifecycle → iac-orchestrator → multi-cloud stages.
It does not copy UAT wildcard claims. Changing that caller requires reviewing
this identity contract, rather than widening its workflow allowlist.

The existing policy template is reused without changing capabilities: four
read-only provider/account and state paths under the selected Dev environment.
This change adds no KV values, provider credentials, root token or dispatch
input. Fake-CLI tests prove rendering and fail-closed claim validation, not
actual Vault login or provider access. Applying the role/policy has **not been
authorized or performed**; a reviewed template is only the proposed identity
configuration. A policy-management operator with the separately authorized
scope would apply it through the existing bootstrap entrypoint.

The separate managed role `github-actions-playbooks-dev-k3s-bootstrap`
uses the same main-only lifecycle caller and the fixed Playbooks
`dev-k3s-bootstrap.yml@e4607530b545ccf09e4045113afeb644b067823e` job from
Playbooks #805. Its policy reads only `kv/data/CICD/dev/k3s-bootstrap`, with no
metadata/list/write access. It can be selected by the existing managed-role
entrypoint's `--role` path; no new administrator CLI is introduced. A feature
branch lifecycle dispatch is deliberately outside these proposed main-only
claims and cannot be used to validate them. Role publication, actual workload
login and bootstrap remain unrun and require their existing authorization.
