# 特性泳道与 Serverless 最新验收目标

关联 [#1445](https://github.com/ai-workspace-infra/Platform-Orchestrator/issues/1445)、[#1468](https://github.com/ai-workspace-infra/Platform-Orchestrator/issues/1468)。

完整链路：Feature ID → 跨仓库 PR → 固定候选 → 独立 SIT 泳道 → 组合验证 → 合并 Main → 自动构建并锁定 Main 快照 → Serverless UAT 发布与健康检查 → 归档回收。

## 基线与本次修复

Main `7eeaedaa7e18ce3c617ed13967da978d1109ee08` 含 PR #1471–#1474。Serverless run `40627929478` 的 init 已有 Vault OIDC 登录证据，但初始化、前端发布和探针为输出占位；实际 Cloud Run 部署与 serving digest 检查跳过。Main 快照 run `40627892489` 在共享平台 readiness 失败。

本次在取凭据或派发前阻断未接通的变更操作；plan 要求 DNS 不变更。汇总只生成 PLAN_ONLY 或 BLOCKED，附 workflow SHA、run ID、attempt，回执缺失必须失败。快照派发改用 environment/release_tag，自动 Serverless 仅允许 UAT。

本次是临时失败保护，尚未完成 owner 接通、五阶段重构或 UAT 发布；不能通过移除门禁恢复发布。

## 后续顺序与验收

1. 核验并交付固定 SHA 的 Cloudflare、Cloud Run、Registry、Supabase owner 初始化与升级能力，再切换 caller；不把执行逻辑复制到控制面。
2. UAT、PROD 通过参数共用实现，恢复“准备 → 后端矩阵 → 前端矩阵 → 配置 → 汇总”。前端必须等待后端门禁；展开依赖路径最多五层，不删除数据前置检查。
3. 普通 deploy 不隐式初始化、迁移、导入或 checkpoint 写库。显式数据变更保留授权、备份恢复、版本和 SQL checksum 门禁。
4. 冻结各仓 SHA、GitOps SHA、镜像 digest 和前端资产身份，修复 readiness 根因与精确 OIDC claim；同一快照幂等派发，防止陈旧候选覆盖。
5. 用真实 UAT 执行替换临时阻断：核验当前 run/attempt 的 owner 回执、serving revision/digest、前端资产、域名、公网及业务健康证据。Job 成功不等于发布成功。
6. PROD 仅手动受控晋级已验收 UAT 构件，验证保护 ref、manifest 来源/digest、审批、健康和回退。任意 tag 不能代替已验收 digest。

## SIT 保留与回收

固定 Feature ID 稳定绑定 Namespace。Main 合并不是删除条件；测试未完成、仍有调试事项或缺少下游验收时保留原泳道。候选变化后旧验收失效，更新证据。

完成测试和下游验收后先归档不可变候选、PR、测试和发布证据，再核对精确 Namespace、所有权及关联资源后受控回收，记录回收 run/attempt。共享资源、PROD 数据和备份不属于临时泳道回收目标。本轮未盘点真实集群，不能声称已自动保留或回收。

rootless 保持低优先级，不捆绑全量重建。
