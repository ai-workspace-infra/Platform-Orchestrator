# Dev Feature SIT 泳道重建交接

更新时间：2026-10-27（Asia/Shanghai）  
目的：交接 XConnect 邀请/推荐功能的多仓库 SIT 泳道实施状态，并说明如何在必要时安全重建临时 Namespace。

## 当前状态

| 项目 | 当前事实 | 状态 |
| --- | --- | --- |
| Dev K3s | 单节点、动态云主机；最后已记录实例 ID `109324752`，节点名 `dev-k3s-v5`。历史集群 UID `163f9544-8fe8-423d-8d1c-e2e064412210` | 执行前必须从当前 CMDB/云 API 重新解析并核对，不能把 IP 或旧实例 ID 当永久身份 |
| 功能候选 | GitOps PR [#606](https://github.com/ai-workspace-infra/gitops/pull/606)，head `49c96fb38e7a51d97054951f53a8edb2e82c3a66`，完整栈 SIT 候选；SIT 端点使用 `onwalk.net`，PostgreSQL 隔离 | PR 当前 OPEN；最近读取到的必需检查通过，部署与业务验收不因此视为通过 |
| 业务 PR | Accounts PR #279 与 GitOps 候选相关 | 不得仅凭 SIT 基础设施 PR 自动合并；按用户合并授权和仓库门禁处理 |
| SIT Namespace | 固定特性 Namespace `feature-xconnect-referral-sit`；成功 prepare 曾记录 UID `077809c4-daed-47eb-a696-8802c3065127` | 该 UID 是历史证据；重建前由 resolver 验证回执、当前身份和 UID。不得手工删除或复用旧 UID |
| UAT | 独立持久 Serverless 平台，跟随 main 的发布契约 | 本次 SIT 重建流程不部署、不清理、不改动 UAT |
| 发布域名 | SIT 使用 `onwalk.net`，与 PROD 的 `svc.plus` 分离 | DNS/TLS 需以实际候选和当前记录为准；本交接不宣称业务域名验收成功 |
| Secrets | Dev 工作流使用现有 Dev Vault 身份和经批准的 GHCR 只读路径 | 不记录或输出密钥值。新增 owner 的精确 OIDC claim 尚未确认已应用到 live Vault |

## 已完成的部署阶段

以下均为 GitHub Actions 执行记录，不是本机 SSH/kubectl 操作：

1. Bootstrap：[`40439068564`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40439068564)。
2. 候选 plan：[`40442755969`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40442755969)。
3. SIT prepare：[`40444907535`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40444907535)，成功回执 artifact `12707064496`，仍未过期；包含 Namespace UID 及候选绑定。
4. seed-admin：[`40445087051`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40445087051)，成功。
5. GitOps submit：[`40445327757`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40445327757)，结果为 `submitted_pending_seed`。
6. initialize 曾尝试两次：[`40446134246`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40446134246)、[`40446438275`](https://github.com/ai-workspace-infra/platform-ops-toolkit/actions/runs/40446438275)，均失败。日志只暴露被保护的 `ValueError` 分类，没有成功回执；底层数据库是否部分初始化未知。

因此当前业务状态是：**SIT 部署/数据库初始化未验收，自动测试与真实邀请/邮件/支付验收尚未通过**。不能将失败的 initialize 推断为完全未执行，也不能复用其旧 Namespace UID 作为后续验证凭据。

## 工作流改动

- Playbooks PR [#810](https://github.com/ai-workspace-infra/playbooks/pull/810) 已合并，实现 SIT-only rebuild owner：校验 feature 所有权和旧 Namespace UID，使用 UID 前置条件正常删除，只接受受支持的 `local-path`/Delete 回收结果，等待 Namespace/PV 清理后创建新 Namespace 并重新投影 registry 配置。遇到未知/保留卷、遗留 PV、finalizer 卡住或所有权不符即停止，不强删。
- Playbooks PR [#811](https://github.com/ai-workspace-infra/playbooks/pull/811) 已合并，最终 reusable workflow 固定 SHA 为 `ce62d2ed3ea5f3e2e8d5c298f4f2aa7806e5b69a`，检出实现 SHA `e589b3dd8fca9c51061011f75a87034f6e4ba303`。
- Toolkit PR [#1462](https://github.com/ai-workspace-infra/platform-ops-toolkit/pull/1462) OPEN，head `3747e590f6336e2b9574027ecfacb6639c98e5d1`。增加 `phase=rebuild`，要求 prior prepare 回执，并认证 rebuild 后的新 Namespace UID 和卷回收证据；workflow 调用上面的固定 Playbooks SHA。required checks 最近一轮全部通过。
- 为完成一次性升级，resolver 只允许 `phase=rebuild` 使用旧 caller workflow blob `361b6a13dc9be3e01ee60aea95096a78e08ce37c` 产生的成功 prepare；其他阶段仍要求 producer 与当前 caller policy 一致。
- Skill PR [#59](https://github.com/ai-workspace-lab/xworkspace-core-skills/pull/59) OPEN，head `a322d9909db04dc291706b9388048a7ff278936c`。把一次明确的 SIT 临时资源授权延伸到该功能后续重试，同时限定集群/namespace/数据范围和正常卷回收，不要求每次重试重复确认。
- PR #1462 的首轮检查发现 OIDC 合同测试漏列新增的精确 Playbooks SHA；已修正现有断言，随后检查全部通过。没有扩大 Vault policy 路径。

## 权限和执行边界

- 用户已授权：SIT 临时 feature Namespace 可相互隔离、自动清理/重建、初始化最新候选 SQL schema；Dev 测试可高度自动化。
- 用户已授权：Dev Vault 角色/策略增量及固定工作流身份；授权不包括生产凭据或生产操作。
- **尚未确认**：把最新 Playbooks callee `dev-feature-flux.yml@ce62d2ed3ea5f3e2e8d5c298f4f2aa7806e5b69a` 精确追加到 live Dev Vault role。应用前要读取并比较 live role/policy，只追加该声明并保留其他字段；不能因仓库声明文件存在就报告 live 已应用。
- 所有远端主机/集群/数据库变更仅由 GitHub Actions 中经审查的 owner 执行；禁止手动 SSH、kubectl、数据库客户端或直接删资源。
- 不操作 UAT Serverless、PROD、GitOps 公共 DNS、共享 Namespace、其他数据库/卷，不合并 Accounts PR #279。

## 后续执行顺序

1. 审阅并合并 Toolkit PR #1462 和技能 PR #59；合并前仍需确认两者最新 head 与检查状态。
2. 通过受控 Vault 流程比较 live Dev role/policy；只增加精确 callee SHA `ce62d2ed3ea5f3e2e8d5c298f4f2aa7806e5b69a`，保留现有 caller/callee、策略及其他字段。记录 live 对照证据，不输出凭据。
3. 执行前重新确认 GitOps PR #606 仍 OPEN、head 仍为 `49c96fb38e7a51d97054951f53a8edb2e82c3a66`、检查完整；重新解析动态实例/集群身份；确认旧 prepare artifact `12707064496` 未过期且所有字段仍绑定同一候选和目标。
4. 在 Toolkit `main` 上 dispatch `operation=feature, phase=rebuild, stage=sit, candidate_pr=606`，并引用已核验的固定 locators：foundation run `40439068564`、summary artifact `12706040839`、bootstrap artifact `12705453829`、provenance run `40442755969`/artifact `12706334332`、prepare run `40444907535`/artifact `12707064496`。dispatch 前逐一通过 GitHub API 检查仍可读、未过期且回执匹配；不得仅凭本文 ID 直接执行。
5. 检查 rebuild 回执：候选/实例/集群绑定一致；旧 UID 与新 UID 不同；`namespace_deleted=true`、`persistent_volumes_reclaimed=true`；没有未知/保留卷。任何一项不符即停止，不手工补删。
6. 用新 rebuild run/artifact 继续 seed-admin、submit、initialize、verify；候选不变时仍按 owner 回执校验。initialize 若再次失败，不循环重试，先通过受控 owner 诊断失败分类和数据库状态，再决定是否产生新候选/重建。
7. 只有 verify/自动化及必要真实业务用例有外部回执后，才报告 SIT 验收结果。合并业务 PR、UAT 发布属于后续阶段，按各自授权和候选契约处理。

## 重建停止条件

namespace UID、集群 UID、动态实例、候选 SHA、owner 标签任一不符；namespace 不存在但残留 PV 指向该泳道；出现非 local-path、Retain 或未知 volume；回收等待超时；旧回执不再有效；Vault 角色不包含精确 owner claim；均应失败关闭。不得改为 `--force`、移除 finalizer、手工建同名 Namespace 或跳过回执校验。

