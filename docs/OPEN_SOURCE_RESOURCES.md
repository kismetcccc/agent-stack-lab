# 后端学习资料索引：沿着一次任务读上游文档

> 核对日期：**2026-10-22**。这不是技术大全，也不是第三方文档镜像。这里只选 11 组能解释本项目真实模块的官方资源，并配上代码入口与小练习。

先读 [架构与调用顺序](ARCHITECTURE.md) 和 [组件职责](COMPONENTS.md)，接口字段以 [API 契约](API_CONTRACT.md) 为准。遇到“为什么这样写”，再打开对应上游章节，不必从头通读每个产品手册。

## 先分清三件事

1. **官方公开文档**：公开可读，不代表可以整页复制、翻译后再分发。本页只保留外链和原创中文导读；没有搬运第三方文档或代码。
2. **OSI 开源代码与 source-available 代码**：下文按具体版本区分。尤其不能把 `mongo:8.0.6` 和 `redis:7.4.2` 一并标成 MIT、Apache-2.0 或 OSI 开源。
3. **本项目自身的许可**：本项目尚未选择开源许可证。本页记录的都是上游许可，不为本项目选择或添加 `LICENSE`，也不自动授权复制上游内容。代码仓库主许可证不一定覆盖全部第三方依赖、镜像层、商标和外部网站文档；复用前要检查目标文件及其单独声明。

下表的版本来自 [uv.lock](../uv.lock)、[默认 Compose](../compose.yaml) 与明确标注的草稿，不表示“最新”“仍受支持”或“无漏洞”。固定 tag 也不等于固定镜像 digest。主分支和 `latest` 文档会变化，升级时应重新核对；本页不是完整依赖许可证清单或合规审计。

## 阅读路线与当前边界

| 顺序 | 想回答的问题 | 资源 | 本项目状态 |
|---|---|---|---|
| 初次运行先看 | 为什么数据库启动后，还要等迁移完成？ | 8. Docker Compose | 默认后端运行入口 |
| 1 → 2 | HTTP 请求怎样变成校验过的输入？ | FastAPI → Pydantic | 已接入 API |
| 3 → 4 | 一次请求怎样原子地写入任务与待发事件？ | SQLAlchemy → MySQL | 已接入事务与状态权威 |
| 5 | 消息重复、Worker 重启后为何还能继续？ | Kafka | 已接入 Outbox / Inbox 链路 |
| 6 → 7 | 结果正文放哪？缓存坏了为什么不能丢任务？ | MongoDB → Redis | 已接入结果与可丢弃缓存 |
| 9 | 怎样统计请求次数、耗时，而不是伪造进度？ | Prometheus | API 指标已接入；采集服务仍是草稿 |
| 后续 10 → 11 | 如何串联跨进程追踪，再理解部署探针？ | OpenTelemetry → Kubernetes | 后续学习；不纳入当前已验收能力 |

这里的“已接入”是源码事实，不是本页重新跑过所有集成测试。实际验收看 [测试报告](TEST_REPORT.md) 与 [单 Agent 报告](AGENT_TEST_REPORT.md)。小练习是学习建议，不是本次目录编写的执行记录。需要停服务的练习只在独立开发栈、使用合成数据与 deterministic 模式执行；操作后恢复服务，不删除数据卷。

## 1. FastAPI：HTTP 边界，不是业务执行器

- **版本 / 状态 / 核对**：`fastapi==0.159.1`（`uv.lock`）；API 已接入；2026-10-22。
- **学什么、为什么**：理解请求体、路由、错误响应与同步/异步调用的边界。HTTP 层负责接受和拒绝请求，不应承担整个后台任务执行循环。
- **先读 → 再读**：[Request Body](https://fastapi.tiangolo.com/tutorial/body/) → [Concurrency and async / await](https://fastapi.tiangolo.com/async/)。重点区分框架调用普通 `def` 路由与自己在异步函数中调用阻塞代码。
- **对应本仓库**：[backend/app.py](../backend/app.py) 的 `create_app`、`context`、`submit` 与异常处理器；顺着 `submit` 进入 [TaskService.create](../backend/service.py)，不要在路由里寻找 Kafka 消费循环。
- **小练习**：在已有合法会话下，对比“缺少幂等键”“空白 prompt”“正常提交”的响应；再指出哪些拒绝发生在业务写入之前。正常 `202` 仅代表接单，不代表任务完成。
- **源码与许可证据**：[fastapi/fastapi](https://github.com/fastapi/fastapi)；[0.159.1 LICENSE](https://github.com/fastapi/fastapi/blob/0.159.1/LICENSE) 为 **MIT（OSI 开源）**。这是代码许可定位，不将所有外部网页都默认视为 MIT。

## 2. Pydantic：把输入和输出约束写成可检查的契约

- **版本 / 状态 / 核对**：`pydantic==2.14.1`（锁文件中的间接依赖，应用直接使用其 API）；已接入；2026-10-22。
- **学什么、为什么**：类型与字段限制负责结构校验，自定义 validator 负责额外规则。字段是字符串，不代表它不是纯空白；响应 schema 也不等于资源授权。
- **阅读顺序**：[Validators](https://pydantic.dev/docs/validation/latest/concepts/validators/) 的 field validator 与执行顺序 → 回到项目的 `Field` 限制和响应模型。链接是滚动文档，阅读时以锁定的 v2 API 为准。
- **对应本仓库**：[backend/app.py](../backend/app.py) 的 `TaskInput.trim`、`Credentials`、`AgentStep`、`AgentStepsResponse`、`ResultResponse`。`Literal` 限定动作类型和模型模式；所有权检查仍在业务层。
- **小练习**：分别用空串、三个空格、正常文本调用 `TaskInput.model_validate`，写下 Field 与 trim 各自拦住什么；再检查 HTTP 层为何只返回安全的统一 `422`，不回显完整输入。
- **源码与许可证据**：[pydantic/pydantic](https://github.com/pydantic/pydantic)；[v2.14.1 LICENSE](https://github.com/pydantic/pydantic/blob/v2.14.1/LICENSE) 为 **MIT（OSI 开源）**。

## 3. SQLAlchemy：明确事务生命周期，而不是把 ORM 当魔法

- **版本 / 状态 / 核对**：`sqlalchemy==2.1.6`；已接入；2026-10-22。这里选 **2.1 文档**，不把旧 2.0 页面当成精确版本依据。
- **学什么、为什么**：Session、flush、commit、rollback 不是同一件事。只有清楚事务何时结束，才能解释任务与 Outbox 的原子性，以及为什么慢模型调用必须放在事务外。
- **阅读顺序**：[Session Basics 2.1](https://docs.sqlalchemy.org/en/21/orm/session_basics.html) 中 begin/commit/rollback → flushing → Session 使用边界。
- **对应本仓库**：[backend/db.py](../backend/db.py) 的 `connect` / `sessionmaker`；[backend/service.py](../backend/service.py) 的 `create`、`claim`、`finalize`、`execute_once`。数据库表 `Session` 是登录会话表，不要与 SQLAlchemy ORM Session 混淆。
- **小练习**：给 `create` 标出事务开始、`flush`、Outbox 插入和提交点；再为 `execute_once` 画两个短事务框，说明模型执行为什么不在框内。
- **源码与许可证据**：[sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy)；[rel_2_1_6 LICENSE](https://github.com/sqlalchemy/sqlalchemy/blob/rel_2_1_6/LICENSE) 及[官方许可说明](https://www.sqlalchemy.org/download.html#license)为 **MIT（OSI 开源）**。

## 4. MySQL：状态权威、并发约束和领取任务

- **版本 / 状态 / 核对**：默认镜像 `mysql:8.4.7`；已接入；2026-10-22。
- **学什么、为什么**：事务保证一组写入共同提交；唯一约束兜住并发竞态；锁定读取让领取任务与改状态成为受保护的一步。`SKIP LOCKED` 适合避开正被领取的工作，不是“查询结果永远完整”的承诺。
- **阅读顺序**：[8.4 Locking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html) 的 `FOR UPDATE` → `NOWAIT` / `SKIP LOCKED` → 回到业务状态机。
- **对应本仓库**：[backend/db.py](../backend/db.py) 的 `Task` 唯一约束、`Outbox`、`Inbox`、`Attempt`；[backend/service.py](../backend/service.py) 的 `claim`、`finalize`、`recover`。fence 与租约是应用协议，不是数据库自动提供的“模型只执行一次”。
- **小练习**：阅读 [test_concurrent_idempotency_and_conflict](../tests/integration/test_chain.py)，预测同键同参数和同键不同参数的区别；解释为什么先查一次数据库，仍不能删掉唯一约束。
- **源码与许可证据**：[mysql/mysql-server](https://github.com/mysql/mysql-server)；[mysql-8.4.7 LICENSE](https://github.com/mysql/mysql-server/blob/mysql-8.4.7/LICENSE) 中 Community Server 主许可为 **GPLv2（OSI 开源）**，并包含附加许可及第三方声明。不能把整个镜像所有内容一概标成 GPL；官方手册也不因服务端代码采用 GPL 就自动适用同一许可。

## 5. Apache Kafka：交付事件，而不是裁决任务状态

- **版本 / 状态 / 核对**：默认镜像 `apache/kafka:4.0.0`；已接入单节点 KRaft 教学环境；2026-10-22。
- **学什么、为什么**：区分生产者确认、消费位点、业务事务与重复投递。Kafka 内部的幂等/事务能力不能直接覆盖 MySQL、MongoDB 与模型调用组成的完整链路。
- **阅读顺序**：[Kafka 4.0 Design](https://kafka.apache.org/40/design/design/) 中 Message Delivery Semantics → Consumers / Consumer Position；再看本项目每个提交点。
- **对应本仓库**：[KafkaBus.publish](../backend/adapters.py) → [TaskService.relay_once / receive](../backend/service.py) → [worker.main](../backend/worker.py)。Inbox 落库之后才提交 offset；发布确认后、Outbox 标记前仍可能重发。
- **小练习**：沿着 [test_full_chain_and_duplicate_event](../tests/integration/test_chain.py) 的重投部分，列出不应增加或回退的记录；用两句话解释“相同 event_id 重投安全”为什么仍不等于模型只调用一次。
- **源码与许可证据**：[apache/kafka](https://github.com/apache/kafka)；[4.0.0 LICENSE](https://github.com/apache/kafka/blob/4.0.0/LICENSE) 为 **Apache-2.0（OSI 开源）**。客户端与其依赖另有许可，不能仅由 broker 许可证推出。

## 6. MongoDB：保存灵活结果，但不与 MySQL 争夺权威

- **版本 / 状态 / 核对**：默认镜像 `mongo:8.0.6`；结果文档已接入；2026-10-22。
- **学什么、为什么**：单文档原子写入与跨系统原子事务不同。稳定 `_id` 配合仅首次插入字段，帮助同一结果重复保存；能否正式展示成功，仍由 MySQL 已提交的结果引用决定。
- **阅读顺序**：[MongoDB 8.0 Atomicity and Transactions](https://www.mongodb.com/docs/v8.0/core/write-operations-atomicity/) 的单文档边界 → 对照项目“先写文档、再提交引用”的顺序。
- **对应本仓库**：[MongoDocuments.save / get](../backend/adapters.py)；[TaskService.execute_once / finalize / document](../backend/service.py)。结果 ID 属于具体 attempt；旧 attempt 的孤儿文档不是正式结果。
- **小练习**：按 [故障实验 D](FAILURE_LABS.md) 在纸上推演“Mongo 已写入、MySQL 尚未成功”时，任务、结果接口各能返回什么；不能把孤儿文档存在解释为已成功。
- **源码与许可证据**：[mongodb/mongo](https://github.com/mongodb/mongo)；[r8.0.6 LICENSE-Community.txt](https://github.com/mongodb/mongo/blob/r8.0.6/LICENSE-Community.txt) 为 **SSPL v1（source-available，不是 OSI 开源许可证）**，参见 [OSI 说明](https://opensource.org/blog/the-sspl-is-not-an-open-source-license)。[MongoDB 官方许可页](https://www.mongodb.com/legal/licensing/community-edition)另外区分服务端、驱动和文档，不能把驱动的 Apache-2.0 套给服务端，也不能反向套用。

## 7. Redis：可丢弃的加速层，必须能降级

- **版本 / 状态 / 核对**：默认镜像 `redis:7.4.2`；结果 cache-aside 与非权威进度已接入；2026-10-22。
- **学什么、为什么**：先查缓存、未命中再查正文存储，配合 TTL 控制生命周期。缓存丢失不能改变任务状态，也不能绕过 SQL 所有权检查。
- **阅读顺序**：[官方 cache-aside 指南](https://redis.io/docs/latest/develop/use-cases/cache-aside/) → 对照本项目不可变结果引用和降级分支。指南中的更多产品功能不代表本项目已经采用。
- **对应本仓库**：[ProgressCache](../backend/adapters.py) 的 `read_result` / `store_result`；[TaskService.document](../backend/service.py)。结果缓存 TTL 为 300 秒，`hit`、`miss`、`unavailable`、`disabled` 含义不同。
- **小练习**：读同一成功结果两次，记录 `cache_status`；缓存已热时首次也可能命中。完成 [Redis 故障练习](FAILURE_LABS.md) 后确认仍可回源 MongoDB，并说明为什么 MySQL 不可用时不能靠缓存跳过授权。
- **源码与许可证据**：[redis/redis](https://github.com/redis/redis)；[7.4.2 LICENSE.txt](https://github.com/redis/redis/blob/7.4.2/LICENSE.txt) 为 **RSALv2 或 SSPLv1（source-available；本页不列为 OSI 开源）**。[官方版本许可表](https://redis.io/legal/licenses/)区分 7.2 及以前、7.4、8+；不能把旧版 BSD 或新版可选 AGPLv3 回套到当前 `7.4.2`。Python 客户端也不是 Redis 服务端本身。

## 8. Docker Compose：把真实依赖按可复现顺序启动

- **版本 / 状态 / 核对**：默认 `compose.yaml` 已采用；[基础设施说明](../infra/README.md)记录过 CLI `v2.35.1` 的结构验证，但宿主机 CLI 不是该文件锁定的镜像依赖；2026-10-22。
- **学什么、为什么**：容器 running 不等于服务 ready；健康检查、迁移完成条件和应用启动顺序分别解决不同问题。Compose 管启动，不替业务实现幂等或数据备份。
- **先读 → 再读**：[启动顺序与 depends_on](https://docs.docker.com/compose/how-tos/startup-order/) → [profiles](https://docs.docker.com/compose/how-tos/profiles/)。默认后端、可选 UI 覆盖文件和完整基础设施草稿要分开看。
- **对应本仓库**：[compose.yaml](../compose.yaml) 的 healthcheck / depends_on / migrate；[compose.ui.yaml](../compose.ui.yaml)；[infra/drafts/compose.full.yaml](../infra/drafts/compose.full.yaml) 只是后续草稿。
- **小练习**：画出“MySQL 就绪 → migrate 成功 → API / Worker”的依赖图；在已初始化的独立环境用 `docker compose config --quiet` 只检查结构，再用 `docker compose ps` 查看运行状态。前者通过不能代替后者；不要公开展开后的完整配置或凭据。
- **源码与许可证据**：[docker/compose](https://github.com/docker/compose)；[v2.35.1 LICENSE](https://github.com/docker/compose/blob/v2.35.1/LICENSE) 为 **Apache-2.0（OSI 开源）**。这是 Compose 代码许可，不是 Docker Desktop 订阅或 Docker Docs 网站的统一许可结论。

## 9. Prometheus：测量实际请求，不把指标当业务账本

- **版本 / 状态 / 核对**：`prometheus-client==0.26.0` 已接入；`prom/prometheus:v3.3.0` 只出现在完整基础设施草稿，未因此成为默认已验收服务；2026-10-22。
- **学什么、为什么**：Counter 记录累计次数，Histogram 记录耗时分布。标签要表达有限类别，不能用每个 task_id、原始 URL 或用户输入制造无限时序和信息泄露。
- **先读 → 再读**：[Python 客户端 Instrumenting](https://prometheus.github.io/client_python/instrumenting/) → [Instrumentation 实践](https://prometheus.io/docs/practices/instrumentation/)。
- **对应本仓库**：[backend/app.py](../backend/app.py) 的 `REQUESTS`、`LATENCY`、`context`、`/metrics`；[prometheus.yml](../infra/observability/prometheus.yml) 是采集配置，不是采集已成功的证据。
- **小练习**：先读 `/metrics`，访问一次 `/healthz` 后再读；找到对应请求计数变化，并解释为什么任务详情使用路由模板标签，而不是为每个真实任务 ID 建一组指标。
- **源码与许可证据**：[prometheus/client_python](https://github.com/prometheus/client_python) 的 [v0.26.0 LICENSE](https://github.com/prometheus/client_python/blob/v0.26.0/LICENSE)，以及服务端 [v3.3.0 LICENSE](https://github.com/prometheus/prometheus/blob/v3.3.0/LICENSE)，主许可证均为 **Apache-2.0（OSI 开源）**；二者是独立组件。客户端 0.26.0 的发行包许可表达式另列 `Apache-2.0 AND BSD-2-Clause`，须同时检查其附带许可/NOTICE，不能把主 LICENSE 当成所有内含文件的完整许可结论。

## 10. OpenTelemetry：后续理解“关联 ID”与完整 tracing 的差别

- **版本 / 状态 / 核对**：草稿镜像 `otel/opentelemetry-collector:0.123.0`；**后续阅读，当前没有完整应用埋点/导出链路验收**；2026-10-22。
- **学什么、为什么**：日志、指标、trace 回答不同问题；跨 HTTP、消息与 Worker 的上下文传播需要显式设计。有一个叫 `trace_id` 的字段，不代表已经产生、传播并导出了标准 span。
- **阅读顺序**：[Observability primer](https://opentelemetry.io/docs/concepts/observability-primer/) → [Context propagation](https://opentelemetry.io/docs/concepts/context-propagation/) → [Collector configuration](https://opentelemetry.io/docs/collector/configuration/)。后两章可留到扩展时，不需要先部署整套系统。
- **对应本仓库**：[TaskService.emit / audit](../backend/service.py) 中现有业务关联 ID；[otel.yml](../infra/observability/otel.yml) 的 receiver → processor → debug exporter。`pyproject.toml` 尚未声明 OTel SDK；配置文件存在不等于应用正在发出 trace。
- **小练习**：在现有调用图上圈出未来需要注入/提取上下文的位置，再列出还缺少的 SDK、span、导出和查询验证；只做设计，不将预想 span 写成真实运行轨迹。
- **源码与许可证据**：[open-telemetry/opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector)；[v0.123.0 LICENSE](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.123.0/LICENSE) 为 **Apache-2.0（OSI 开源）**。

## 11. Kubernetes：后续部署章节，不用它掩盖业务一致性问题

- **版本 / 状态 / 核对**：[Kind 配置](../infra/k8s/kind.yaml) 中 `kindest/node:v1.32.2`；清单已保留，**按当前 Agent.md 范围继续延期，不宣称部署已验收**；2026-10-22。
- **学什么、为什么**：存活探针解决是否重启，就绪探针解决是否接收流量；网络策略需要网络插件执行。增加副本不会自动修复重复消息、租约或单实例 relay 的约束。
- **先读 → 再读**：[Liveness / Readiness / Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/) → [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)。这是当前概念文档，具体部署前还须核对目标集群版本，不能把新版本特性直接套到草稿的 1.32.2。
- **对应本仓库**：[infra/k8s/04-app.yaml](../infra/k8s/04-app.yaml)、[05-network-policies.yaml](../infra/k8s/05-network-policies.yaml) 与 [app.py](../backend/app.py) 的 `/healthz`、`/readyz`。默认 Compose 学习不要求同时启动集群。
- **小练习**：只读清单，找出 API 的 liveness 和 readiness 各指向哪个端点；预测数据库暂时离线时哪些探针应失败。再解释为什么仅提交 NetworkPolicy YAML 不能证明网络隔离已生效。
- **源码与许可证据**：[kubernetes/kubernetes](https://github.com/kubernetes/kubernetes)；[v1.32.2 LICENSE](https://github.com/kubernetes/kubernetes/blob/v1.32.2/LICENSE) 为 **Apache-2.0（OSI 开源）**。这不是 Kind 节点镜像内所有组件的统一许可证。

## 如何维护这份目录

- 更新依赖或镜像后，同步版本、对应章节和许可证链接；不要只改成“最新版”。
- 保留“已接入 / 草稿 / 延期”的区别；新增测试结果应写入对应报告，不把上游教程当作本项目验收证据。
- 只收录能对应实际模块或明确后续章节的资料。当前已经用 Kafka 教交付语义，不再为凑数量加入第二套消息队列。
- 分享学习成果时，写自己的理解、实验条件和观察结果；引用小段内容也保留来源。需要复制上游代码或文档时，另行检查具体许可、署名、NOTICE 和分发义务。
- 本次已检查官方文档、GitHub 仓库和上述版本许可证；部分 GitHub 页面通过只读 GitHub 文件接口核对。链接有效性是该日期的观察，不保证永久可访问；这也不等于检查了每个镜像的全部内容。

未来讨论本项目许可证时，可从 OSI 的 [MIT](https://opensource.org/license/MIT)、[Apache-2.0](https://opensource.org/license/apache-2.0) 与 [GPLv2](https://opensource.org/license/gpl-2.0) 原文了解差异。这里只提供阅读入口，**不替维护者做许可选择**。
