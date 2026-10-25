# V4 → V5：23 组正式验收矩阵

执行顺序：SSH → Playbook → Role；完成 owner 验证及 UAT 后，由现有迁移流程结束后的 dispatch 调用 job 矩阵。本次不新增或修改 GitHub Workflow。

“用户历史快照”保留原表结果；“最近只读采样”为 2026-10-25 17:38（北京时间），并非本次新执行。未采样项不继承历史 PASS。阶段编号表达生命周期，不表示阶段已执行。

| 编号 | 验收内容 | 阶段 | 框架 / 责任方 | 用户历史快照 | 最近只读采样 |
|---|---|---|---|---|---|
| V5-01 | DNS 四条记录与切流目标 | S5 | dnspython + IaC / iac_modules | PASS | NOT_RUN |
| V5-02 | TLS / 路由 / 首页 / 登录页 | S4、S5 | pytest + httpx / playbooks | PASS | NOT_RUN |
| V5-03 | Console / Accounts / Billing 健康 | S4 | pytest + Playbooks / playbooks | PASS | NOT_RUN |
| V5-04 | 登录 POST / 业务校验 | S4、S6 | pytest + Playwright / playbooks | 路由 PASS | NOT_RUN |
| V5-05 | Session / Billing 鉴权 | S4、S6 | pytest + httpx / playbooks | 匿名拒绝 PASS | NOT_RUN |
| V5-06 | Schema 版本与 dirty 状态 | S3 | psycopg + pytest / playbooks | PASS | PASS |
| V5-07 | 业务数据数量与迁移基线 | S3、S6 | SQL + pytest / playbooks | PASS | PARTIAL |
| V5-08 | 订阅外键完整性 | S3 | SQL + pytest / playbooks | PASS | PASS |
| V5-09 | 身份字段与批准例外 | S3 | SQL + 摘要对账 / playbooks | PASS | NOT_RUN |
| V5-10 | 实时流量采集与入账 | S4、S6 | pytest + VictoriaMetrics / playbooks | PARTIAL | PARTIAL |
| V5-11 | Agent 心跳覆盖率 | S4、S6 | pytest + Agent API / playbooks | PARTIAL | FAIL |
| V5-12 | 区域池 API 与页面一致性 | S6 | pytest + Playwright / playbooks | 待验证 | NOT_RUN |
| V5-13 | Flux / ESO / GitOps Drift | S2、S4 | flux + kubectl + pytest / playbooks | PARTIAL | PARTIAL |
| V5-14 | Vault Raft / KV 一致性 | S1、S2 | hvac + Playbooks / playbooks | PARTIAL | NOT_RUN |
| V5-15 | Grafana / Dashboard / Alert | S4、S6 | Grafana API + pytest / playbooks | PARTIAL | NOT_RUN |
| V5-16 | 真实登录与完整业务页面对账 | S6 | Playwright / playbooks | 待验证 | NOT_RUN |
| V5-17 | 三轮部署幂等与状态收敛 | S7 | Ansible + pytest / playbooks | NOT_RUN | NOT_RUN |
| V5-18 | 隔离、故障恢复、回滚验证 | S7 | Ansible + 故障注入测试 / playbooks | NOT_RUN | NOT_RUN |
| V5-19 | Clean Rebuild | S1 | IaC + Playbooks / iac_modules | 未提供 | NOT_RUN |
| V5-20 | Migration Provenance | S0、S3 | Playbooks + migratectl + pytest / playbooks | 未提供 | NOT_RUN |
| V5-21 | Single Writer Handoff | S5 | Playbooks + SQL + pytest / playbooks | 未提供 | NOT_RUN |
| V5-22 | Cutover & Rollback | S5、S7 | Toolkit 门禁 + IaC DNS + Playbooks 恢复 / platform-ops-toolkit | 未提供 | NOT_RUN |
| V5-23 | Evidence Contract | S0、S8 | Toolkit + pytest 契约测试 / platform-ops-toolkit | 未提供 | NOT_RUN |

## 每组通过条件

- **V5-01**：四条权威解析记录符合已批准目标；记录 TTL、实际地址及切流前后采样。
- **V5-02**：证书链、有效期、SNI 与预期主机一致；首页和登录页返回预期内容及状态。
- **V5-03**：所有声明服务健康且依赖数据库就绪；返回实际部署版本。
- **V5-04**：空/无效输入返回业务校验错误；真实登录另需有效凭据和页面证据，路由通过不能代替登录。
- **V5-05**：匿名 Session 与无凭据采集被拒绝；授权成功路径与越权拒绝分别验证。
- **V5-06**：Schema 等于固定候选声明且 dirty=false；SQL 只读事务且错误立即失败。
- **V5-07**：数量、业务摘要、源快照边界与迁移基线一致；目标独有事实保留；只看数量不足以通过。
- **V5-08**：订阅用户引用无孤立记录；相关引用按声明检查。
- **V5-09**：身份字段逐项摘要一致；例外带独立审批依据、字段、主体和适用版本，禁止泛化跳过。
- **V5-10**：Exporter→Vector→Billing→PostgreSQL→Accounts 新鲜度、入账幂等及账户页面一致；正流量桶仅为部分证据。
- **V5-11**：登记集合与声明节点集合一致，全部节点在约定周期内心跳；缺任一必需节点即门禁失败。
- **V5-12**：按账户权限核对区域池 API、可选节点及页面；nodes 表为空不得单独判失败。
- **V5-13**：固定 GitOps SHA、资源 Ready、ESO 同步及实时语义差异均满足；Ready 不代替漂移检查。
- **V5-14**：Raft 健康、解封及双端批准范围内 KV 键集合和运行时内存摘要一致；不输出秘密或持久化值。
- **V5-15**：实际面板查询有正确环境新鲜样本，规则求值及受控告警闭环通过；文件存在不等于查询可用。
- **V5-16**：真实登录后用户、套餐、订阅、配额、账单、区域池、用量逐页与 API/数据库对账。
- **V5-17**：同一固定候选连续三轮收敛，无额外业务事实、非预期漂移或无必要重启。
- **V5-18**：先 UAT 受控隔离和业务数据恢复，验证不变量、权限、应用连接、RPO/RTO 及恢复路径。
- **V5-19**：V5 由空环境按声明重建，无意外继承 V4 运行资源；独立资源/state/卷事实可追溯。
- **V5-20**：源端、目标端、快照、Schema、版本、数据摘要及迁移计划均可追溯。
- **V5-21**：所有 API、后台任务、Webhook、消费者及直连写者纳入隔离，任一时刻仅一个授权主端，交接前后对账一致。
- **V5-22**：切流前后 DNS、路由、鉴权、业务及恢复条件满足预期；目标有新写入后不能仅切 DNS 回旧库。
- **V5-23**：必需执行器回执来源可验证，绑定环境、主机、固定 SHA、运行/attempt、artifact 与检查集合，缺失/不符/跳过均阻断。

V5-23 的离线负向测试通过，不等于完整 owner→caller→artifact→门禁链路通过。最新观察仍为 FAIL，不能关闭全流程验收。

当前已实现的首批 Role 覆盖 V5-06、07、08、10、11、13 的只读子集；其余框架和完整断言属于待实施范围，不能因列入矩阵而标记完成。
