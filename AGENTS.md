# Platform-Orchestrator Agent 约束：只做最上层编排调度

Platform-Orchestrator 只负责跨仓调度：输入选择、审批与授权、DAG、调用 owner、等待与关联运行、汇总回执和最终状态。不得成为下列仓库的第二套实现：

| Owner | 职责 |
| --- | --- |
| IaC / `iac_modules` | 云资源、DNS、State、云事实及 CMDB 产出 |
| GitOps / `gitops` | 环境拓扑、资源配置、版本引用、Flux 声明和非敏感配置引用 |
| Artifacts / `artifacts` | 应用制品构建、镜像与 chart 打包、发布及制品元数据 |
| Playbooks / `playbooks` | 主机、服务、身份、数据库、备份恢复、迁移及健康检查执行 |

基础仓库来源由 dispatch 参数选择，默认 `main`；每次运行记录实际解析的 SHA。业务制品版本独立选择。

已有 workflow 依赖不是执行实现或资源声明留在本仓的理由。清理时追踪间接调用，把实现或声明移入对应 owner，切换并验证调用后删除旧副本。本仓只保留调度所需胶水、输入与回执契约及其测试。

本文件是仓库根级强制规则。四边界完整判定见
[`execution-ownership-migration`](https://github.com/ai-workspace-lab/xworkspace-core-skills/blob/main/skills/engineering-standards/execution-ownership-migration/SKILL.md)。

## 必须归 Toolkit 的内容

- GitHub Actions 入口和 `workflow_dispatch`/`workflow_call` 输入校验；
- 环境、目标和不可变 tag/SHA 选择；审批、Vault/OIDC 授权和精确 workflow allowlist；
- 调用固定 SHA 的 Playbooks reusable workflow 与 IaC owner composite action；关联、等待、证据来源和 checksum/digest 校验；
- 最终放行、停止、回滚决策和脱敏发布证据。

## Toolkit 与 Pipeline 的分层

`Toolkit` 是共享控制面；`Pipeline` 是其 GitHub Actions 交付与编排层，负责入口、审批、环境/目标选择、阶段顺序、固定 SHA 派发、运行关联和最终放行。Pipeline 不是新的资源执行 owner；云资源归 IaC Modules，主机/服务/数据库归 Playbooks Roles，目标状态归 GitOps。

## 重复控制逻辑的复用规则

重复的控制面逻辑（输入归一化、环境/目标校验、Vault/OIDC 预检、固定 SHA 派发、子运行关联、证据校验、脱敏和状态映射）必须优先转换为参数化、可版本化的 `.github/actions/<name>/` composite action，并提供明确的 inputs/outputs 与契约测试。

`.github/actions` 不是执行逻辑的迁入点：云资源、DNS、Registry、State 仍归 IaC Modules；主机、服务、数据库、备份、恢复、健康检查仍归 Playbooks Roles；声明式片段仍归 GitOps。Toolkit action 只能调用已审核的 owner workflow/action，不得复制实现或新增 SSH、Provider API、Terraform、Ansible、Docker、systemd、数据库客户端和服务命令。

新增 action 前必须搜索现有 action，证明它消除了重复的控制面代码，且没有形成第二条执行路径。

## 新代码硬禁令

`.github/scripts`、Actions、控制器不得新增或扩展以下执行：`ssh`、`scp`、`ansible*`、`docker`
（仅允许受控镜像元数据只读校验）、`systemctl`、`apt-get`、`psql`、`pg_dump`、`pg_restore`、
`terraform`、`gcloud`、`aws`、`wrangler`、Cloudflare/DNS API 变更。不得直接写主机、服务、
数据库、DNS、云资源或 CMDB。执行逻辑必须迁移到对应 owner，再切换调用方。

现有 `.github/scripts/` 遗留候选由 `scripts/ci/script_ownership_verify.py` 冻结；历史登记不是新增逻辑豁免。
任何新增执行标记、修改冻结脚本或绕过 scanner 的 PR 必须失败。

## PR 必须证明

`owner`、`caller`、副作用边界、固定 SHA、证据来源，以及“新增 owner → 切换 caller → 验证 → 删除旧副本”。
没有真实 UAT 证据时不得声称部署/迁移/回滚完成。

## 六云 IaC action 交接（v0.6）

IaC 专属 targets/self-check/stage/auth/lifecycle/receipt/summary actions 统一保存于 iac_modules/.github/actions。Toolkit 固定 SHA checkout 后通过固定本地 uses 调用，动作与 Terraform 模块版本绑定；Toolkit 持有全部交付 workflows、runner、Environment 审批、DAG 和最终放行，不复制 provider 命令。GitOps 声明缺失或证据未核验时必须阻断。

## Pipeline 可视化规则

每个 workflow 的 `needs` DAG 最长串联链最多 5 个 job（stage），通常为 3–5 个。
矩阵副本和同层并行 job 计作同一深度；改 job 名称不会缩短链路。
同 runner 的顺序校验优先收进 steps；需要独立 runner/权限/审批的阶段保留 owner workflow，
由总控 dispatch、精确关联等待并核验回执。不得为缩图删除门禁、失败传播或 Environment 审批。
子 workflow 也适用此规则。`scripts/ci/workflow_stage_depth_verify.py` 在 CI 强制检查。
`workflow-stage-depth-policy.json` 仅记录五项现存超长链路技术债，禁止新增例外或提高上限；
改短后必须同步降低上限，达到 5 时删除例外。
