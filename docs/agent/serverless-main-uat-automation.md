# Serverless Main → UAT 自动发布

`daily-main-snapshot.yaml` 是 Serverless Web SaaS UAT 的控制面入口。每日 16:00 UTC（Asia/Shanghai
00:00）从各服务仓 `main` 固定七仓快照，等待每个目标仓的真实构建成功证据后，校验完整源组合与
GitOps revision，再派发 `serverless-orchestrator.yml`。Toolkit 主干中快照清单、Serverless 工作流、
对应 actions/scripts 或本工作流自身变化也会触发该路径。服务仓 Main 更新目前由每日任务拾取；
尚未配置逐仓即时事件通知。

自动路径固定目标为 UAT 的 `web-saas` Serverless 拓扑，DNS 不切换、跳过可选 Stripe catalog、
不迁移数据库、不触发 Selfhost、K3s UAT 或 PROD。`website_content_ref` 与 `tag_ref` 使用同一不可变
快照 tag。手动 build-only 仍由 `workflow_dispatch` 的 `deploy_after_build=false` 控制；显式人工
环境派发按 workflow 现有输入和门禁执行。

发布门禁要求 Accounts、Billing、Content、Portal、Edge Gateway、Frontend Router、PostgreSQL 七个
仓库均有同一快照 tag 的 `build_succeeded` 回执，回执 SHA 是完整提交 SHA，tag 仍解析到该 SHA，且
每个仓当前 `main` 仍等于快照 SHA。任一仓在构建期间前进就阻断部署，下一轮重新形成完整组合。GitOps
checkout 和远端 `main` 必须匹配同一 SHA。门禁在 UAT dispatch 前保存 `serverless-main-release/v1`
来源清单与 fingerprint；派发回执引用 fingerprint、快照 tag 和 Serverless child run URL。

该来源清单记录不可变 Git refs/提交，不将 tag 存在或 CI 成功伪称为 UAT 业务验收。UAT child workflow
及其 owner receipts 是实际部署和健康验证证据。Main 更新的事件通知尚未接通时，自动发布时效为每日一次；
直接合并到服务仓 Main 不会立刻启动该 Toolkit workflow。

历史的 `uat_release.py` 面向已删除的 Dev K3s UAT writer 路径，已从控制面移除。持久 UAT 的目标所有权
仍是 GitOps `topology/uat/serverless/runtime-topology.yaml` 与 Serverless Orchestrator。
