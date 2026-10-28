# Platform Orchestrator 文档中心

本仓库经重构后聚焦为 **平台交付编排中心 (Platform Orchestrator)**，负责全环境（UAT、PROD、SIT）的发布流水线编排、质量门禁判定、云平台抽象对接（Cloudflare、Cloud Run、Supabase、K3s）与不可变交付凭据签发。

---

## 一、核心编排流水线全景

| 编排流水线 | 核心职责 | 环境覆盖 | 阶段结构 |
| :--- | :--- | :--- | :--- |
| [`.github/workflows/serverless-orchestrator.yml`](../.github/workflows/serverless-orchestrator.yml) | Serverless 准生产与生产交付 | UAT / PROD | 准备 → DB 服务 → 后端矩阵 → 前端矩阵 → 配置 → 汇总 |
| [`.github/workflows/selfhost-orchestrator.yml`](../.github/workflows/selfhost-orchestrator.yml) | Selfhost 多云 / K3s 平台工程编排 | UAT / PROD | Resolve → IaC → Deploy → Migrate → Verify |
| [`.github/workflows/hybrid-orchestrator.yml`](../.github/workflows/hybrid-orchestrator.yml) | 混合云弹性容灾与双活编排 | UAT | 跨节点调度与故障转移 |
| [`.github/workflows/iac-orchestrator.yml`](../.github/workflows/iac-orchestrator.yml) | 多云基础设施声明式供应 | 多云 | Bootstrap → Account → Resources |
| [`.github/workflows/daily-main-snapshot.yaml`](../.github/workflows/daily-main-snapshot.yaml) | 主干不可变快照与持续集成验证 | Daily | 快照解析 → 并行构建 → 验收编排 |
| [`.github/workflows/environment-data-operations.yml`](../.github/workflows/environment-data-operations.yml) | 数据库操作与迁移执行中心 | UAT / PROD | Checkpoint 快照 → 探针 → 迁移执行 |

---

## 二、编排器操作指南

- [Serverless 编排矩阵与执行语义](howto/serverless-orchestrator-matrix.md)
- [GitOps 运行时路由与前端映射配置](howto/gitops-serverless-routing.md)
- [Prod Selfhost 主干发布状态与推进规范](howto/prod-selfhost-mainline-status.md)
- [UAT 架构解耦与迁移操作手册](howto/uat-split-selfhost-migration.md)
- [统一多云 IaC 状态校验规则](howto/unified-iac-state-validation.md)
- [IaC 自检矩阵操作手册](howto/iac-self-check-matrix.md)
- [多环境不可变镜像 Tag 契约规范](domains/IMAGE-TAG-CONTRACT.md)
- [交付清单与制品约束标准](domains/DELIVERY-MANIFEST.md)

---

## 三、历史参考文档与知识库归档说明

为了保持本仓库作为 **纯净编排控制面** 的高内聚定位，所有历史研发台账、技术白皮书、早期排障演练记录和产品蓝图文档已全量迁移至知识库仓库：

👉 **[ai-workspace-services/knowledge: docs/reference/platform-ops-toolkit/](https://github.com/ai-workspace-services/knowledge/tree/main/docs/reference/platform-ops-toolkit)**

知识库归档目录包含：
- `01-architecture-and-standards/`：平台顶层架构规范与服务划分定义
- `02-delivery-and-orchestration/`：历史编排设计方案与发布标准
- `03-data-operations-and-migration/`：数据库迁移全链路指南与双语灾备
- `04-security-vault-and-iam/`：Vault 密钥分层模型与多云 OIDC 认证手册
- `05-cloud-infrastructure-and-iac/`：多云账户与 IaC 状态契约白皮书
- `06-network-and-xconnect/`：XConnect 零信任网络原则与覆盖组网
- `07-agent-and-execution-ownership/`：四仓职责交接历史审计记录
- `08-runbooks-and-cases/`：生产与 UAT 历史故障案例演练库
- `09-plans-and-blueprints/`：AI Aggregator 聚合网关历史规划
- `10-tasks-archive/`：2026-07 至 2026-10 全周期任务日志底账
- `assets/`：全套 Grafana 监控看板截图与拓扑图
