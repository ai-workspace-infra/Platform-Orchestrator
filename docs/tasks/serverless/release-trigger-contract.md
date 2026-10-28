# Feature、Daily Snapshot 与 Release 触发契约

任务来源：[统一发布 #1445](https://github.com/ai-workspace-infra/Platform-Orchestrator/issues/1445) 和 [Main 自动发布 #1468](https://github.com/ai-workspace-infra/Platform-Orchestrator/issues/1468)。本文件记录目标与待实施门禁，不代表触发器或运行时验收已经完成。

## 三类触发

| 信号 | 目标 | 放行条件 | 后续动作 |
| --- | --- | --- | --- |
| Feature tag | 指定 Feature ID 的独立 SIT Namespace | 受信任事件来源；tag 不可变且可解析至唯一 Feature ID 和候选 revision；候选清单固定跨仓 PR、每仓 head SHA、镜像 digest、Chart、配置与数据基线；校验事件与清单绑定且所有源仓在允许范围 | 使用对应 Namespace 与域名部署固定候选，执行组合验证并记录 run、attempt 和候选指纹；失败保留泳道 |
| Main 合并或每日计划 | 自动构建 Main 快照，进入 Serverless UAT | 与本次 Feature 关联的全部必需 PR 已合入且 SIT 测试证据对应合入组合；固定参与仓 Main SHA、GitOps SHA、构件 digest 或前端资产身份；构建和质量门禁通过 | 生成不可变 daily-build tag 和清单，幂等派发 UAT，验证实际运行版本、端点和业务健康，归档证据 |
| Release tag | 关联已验收的 UAT Daily Build，人工受控滚动发布 PROD | 正式受保护 release tag、可信 UAT 验收回执、来源快照清单及各服务 digest 一一匹配；目标、审批、健康检查与回退条件齐备 | 人工明确选择并启动受保护的 PROD 发布，按滚动步骤验证健康；失败停止并按已批准方案回退 |

Feature tag 的具体仓库归属、格式、tag 创建权限和跨仓事件发送者应由现有受信任发布 owner 的实现决定，不能推断为所有业务仓均已具备事件发送能力。必须验证 tag 的仓库、引用、目标提交和不可覆盖属性，并将解析后的候选指纹绑定 run/attempt；只凭 tag 名或 caller 提供的 JSON 不能放行。不同候选或依赖变化须重新验证。重复事件按 Feature ID 和候选指纹幂等处理，同一泳道串行化；不同 Feature ID 之间保持隔离。

Daily Snapshot 的实际事件覆盖须核验。当前入口包含 Main 指定路径 push、定时和手动触发，不能宣称每个业务仓 Main 合并均会即时触发。跨仓触发须经受信任发送者发往控制面并重新解析真实 Main；事件 payload 不能代替权威仓库事实。锁定后的快照要验证未过期、未被较新候选取代，防止旧运行覆盖 UAT。

PROD 必须同时校验 release 身份与已验收 UAT 的不可变清单；不能因为传入 tag 或格式正确就认为已验收。禁止仅由 tag push 自动执行生产变更。普通 deploy 不隐式执行数据初始化、迁移、导入或写入型 checkpoint。

## SIT 生命周期

Feature ID 稳定关联 `feature-<feature-id>-sit` Namespace 和域名；事件重试不得创建新的匿名泳道。Main 合并不单独触发删除：组合验证、下游验收或调试未完成时保留原泳道。候选、跨仓 PR、测试与发布记录归档并满足回收条件后，核对精确资源和所有权，再受控回收并保存回执。

## 当前缺口与实施顺序

1. 建立 Feature tag 受信任来源和不可变候选清单，连接已有 feature-lane gate 与实际 SIT owner；以负例验证伪造事件、移动 tag、错误 PR/head、缺失 digest 和重复事件。
2. 完成跨仓 Main 合并事件、快照冻结与防旧运行覆盖；修复共享 Observability readiness 当前返回 302 的根因，不绕过门禁。
3. 接通 Cloudflare、Cloud Run、Supabase 的固定 owner 和真实 UAT 健康证据，保持准备 → 后端矩阵 → 前端矩阵 → 配置 → 汇总五阶段。当前入口仍有未接通的执行步骤，临时 admission gate 必须保留，直至真实执行与证据验证完成。
4. 将 Release tag 与已验收 UAT 清单绑定，建立手动审批、滚动发布、健康检查与回退记录；先非生产验证。
5. 关联 Feature ID、tag、PR、构件、测试、发布和归档记录；仅在验收完成后回收泳道。

验收须分别记录静态契约、事件实际触发、SIT 组合测试、UAT 实际运行与生产受控发布；缺失证据标记 NOT_RUN/BLOCKED。当前文档不改变触发器、部署、DNS、数据或集群。
