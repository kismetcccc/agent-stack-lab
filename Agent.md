# Agent Stack Lab：架构蓝图与实施契约

> **当前新增迭代（2026-10-22，1Panel 风格本地控制台，计划优先）**：前一轮组件操作台能力保留，按 `docs/CONSOLE_REDESIGN_PLAN.md` 执行有限的“契约先行 → 前端改版 → 完整测试 → 文档/截图验收 → 保留数据的本机更新”闭环。本轮解决组件混乱：常驻分组导航、紧凑页头与工具栏、资源列表优先、创建/编辑/详情按需抽屉、帮助与操作区分离；四组件不得只换配色，也不得强制同一种内部布局。原有 hash 深链及任务/Agent、架构、学习、故障入口继续有效。
>
> **本轮冻结边界**：个人本地共享教学空间，不新增账号隔离/多租户；保留既有登录、CSRF、Origin、任务所有权和 API 契约。仅前端与相关测试/文档，不新增后端接口/schema/管理命令，不安装 1Panel，不复制其代码/资产，不接 Docker socket，不执行原始 SQL/任意命令，不暴露秘密，不调用真实模型。总览只展示实际接口证据：当前 `/readyz` 没有 Redis 总体探针、Worker 活跃探针或主机指标，不得推断全绿。Redis TTL 与 Kafka producer/consumer 证据保持原真实语义。旧绿色测试不是新布局验收；以最终提交的测试、真实浏览器流程和两尺寸截图作为本轮依据。以下历史阶段完成状态不重新打开。

> **已完成组件操作台迭代（2026-10-22，历史实施契约）**：学习型 v1 已完成，不重新打开旧清单。本轮按 [组件操作台计划与冻结契约](docs/COMPONENT_PLAYGROUND_PLAN.md) 执行有限的「计划 → 实现 → 测试 → 文档 → 本机更新」循环：前端直接操作 MySQL 记录 CRUD、Redis KV/真实 TTL、Mongo JSON CRUD、Kafka 发送/真实消费者收取，不以 Agent 任务或拓扑链路为前置。计划起点为 `b76947dba96978b0cd30991350bb834ab49f48d4`（来源代码父提交 `102491d2`）；既有绿色测试不是新功能已验收。
>
> **本轮边界**：个人本地使用，新增教学数据共享，明确不做 owner/tenant 隔离或账号配额；既有登录/CSRF/Origin 和任务资源所有权保持不变。lab 数据与账号、任务、结果分开，操作固定允许列表、输入/分页/TTL 有界、删除需确认、继续 loopback-only；无原始命令控制台、秘密暴露或模型调用。新 MySQL 表必须有真实 v1→v2 升级与持久数据回归，不把 `create_all` 当升级。Kafka producer 确认和真实 consumer 回执分别展示；Redis 实验不可用必须明确失败，不能复用可降级缓存的假成功语义。云端实现和真实 CI 之后，由协调者使用独立忽略的 `.env.compose.local` 更新已有 `localhost:8081` 栈，保留数据卷和模型配置。以下学习型 v1、单 Agent 和更早阶段记录继续保留原完成状态与范围。

> **已完成学习型 v1 的实施记录（2026-10-22）**：按 [开发任务清单](docs/DEVELOPMENT_PLAN.md) 循环推进后端模块功能、必要的正常/故障测试和完整学习文档。细粒度 AI 评分不再扩展。当前已验收基线 `102491d2` 的 [CI](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39731470818) 已通过 409 项后端/采集器、13 项真实集成、30 项前端单元和 30 项浏览器测试。真实模型只有独立连通性检查，不等于完整 live Agent 验收；默认 CI 仍禁止真实模型调用。下方较早阶段记录保留其当时的提交与范围，最新任务状态以任务清单为准。 本轮四个精确宕机窗口、HTTP 示例及构建上下文保护也通过，详见 [当前报告](docs/DEVELOPMENT_REPORT.md)。

> **历史阶段快照（2026-10-22，运行时 9c4a1908）**：提交 `9c4a1908124b61eee4207dc5bb6cb172134fda06` 已通过140项后端单元/API、13项真实组件集成、30项前端单元、24项桌面/手机浏览器测试；两种尺寸真实Agent动作截图已复核。详见 [单Agent验收报告](docs/AGENT_TEST_REPORT.md)。不得伪造组件在线状态、消息流或进度；Kubernetes和新增外围组件继续延期。

> **单 Agent 契约快照（2026-10-22）**：契约先于实现提交。受限单Agent运行时、成功后动作接口及界面已实现并通过上述教学链路验收；默认scripted_test明确不是LLM推理。真实provider仍关闭、尚未验收，后续需独立配置与验收。边界见 [单Agent最小契约](docs/SINGLE_AGENT.md)，旧echo/单次模型结果不会被包装成Agent轨迹。

> 本文是项目创建时的第一份文件。目标公开仓库：`kismetcccc/agent-stack-lab`。
> 这是面向 AI 学习者的中文后端教学项目，不是生产就绪平台。文中的阶段与能力是实施契约，不代表已经实现或验收。

## 当前范围调整（2026-10-22，优先于后续阶段清单）

先完成的后端阶段聚焦 API、MySQL、Kafka、MongoDB、Redis、逐步代码导读、curl 复现实验与真实集成故障解释。用户随后明确恢复学习型前端，要求简洁、清晰地展示组件能力；前端已完成独立验收，新增外围组件仍暂停。Kubernetes 保留为后续部署章节，当前不展开、不要求运行通过。下方完整阶段保留为学习路线，不是当前全部实现承诺。默认 Compose 只启动后端，API 直接暴露本地 8080（容器内部 8000）。

### 本轮新增范围：受限单 Agent（教学链路已验收，真实LLM未验收）

保留 `{prompt}` 请求，以 `task_input` 表示本任务唯一文本材料；只提供读取文本、字面搜索片段、有限数值统计三个只读工具。单个执行器按“决策 → 工具 → 观察结果 → 再决策/结束”运行，最多六次决策、五次工具调用；60秒执行上限还须受实际租约剩余时间与持久化余量约束。deterministic 是明确标识的脚本测试控制器，live 才是配置并授权后由真实模型选择工具的策略，当前不启用真实调用、不需要凭据。

不改变 MySQL 状态权威、Outbox/Inbox、租约/fencing 或 Redis 缓存语义。`/events` 继续仅表示后台生命周期；已新增 `/agent-steps` 只读取已提交成功结果中的工具动作，运行中/失败尝试的工具轨迹不在本次 MVP 范围。旧结果保留 legacy/单次调用标识，不能包装成 Agent 记录。无上传、任意 shell/文件/网络工具、真实副作用、多 Agent、Kubernetes 或新增编排基础设施。完整字段、预算、错误与验收门槛以 [SINGLE_AGENT.md](docs/SINGLE_AGENT.md) 为本轮设计约束；运行时实施时须同步 API 契约、示例及测试。

## 1. 目标与范围

用一个可运行的 Agent 任务平台理解传统后端主要能力：用户提交任务，后台 Agent 处理，前端查看真实状态、工具步骤与结果。架构清晰优先于组件数量。选择 Python/FastAPI，减少 AI 学习者的语言切换；前端 React + TypeScript。后续可做 Java/Spring Boot 对照章，第一版不维护双后端。

默认在获授权的云端工作区开发；只有另行明确授权的本机任务才操作用户电脑。公共仓库不得包含真实 API key、访问令牌、密码、私有资料或日志中的敏感内容。模型 API 由用户后续提供：交付时提醒通过受保护的环境变量/密钥配置输入，不要求粘贴到公开文件。没有凭据时使用明确标识的 deterministic 测试适配器，绝不能宣称调用了真实模型。

每个功能应标为“计划中 / 已实现未验收 / 已验收 / 阻塞”；只有实际测试证据才支持验收。不得以模拟状态、假进度或静态截图冒充真实集成。

## 2. 架构与模块边界

采用模块化单体，同一后端代码库两个主入口：API 和 Worker。Worker 内部包含 relay、consumer、executor、recovery 模块，不因模块存在就新增微服务。

```text
Browser (React/TypeScript)
  -> reverse proxy (后续网关章节)
  -> FastAPI API -----> MySQL：任务/权限/幂等/Outbox/Inbox/尝试/租约
       |                 ^                       |
       |                 |                       v
       |             Worker executor <--- inbox <- Kafka <- outbox relay
       |                 |
       +---- MongoDB <---+  灵活步骤与结果文档
       +---- Redis          可丢弃缓存与非权威进度
                            后续：对象存储、搜索、可观测性 profiles
```

代码层次：HTTP/schema -> application service -> domain/state machine -> repository/adapters。路由不直接堆砌 SQL、Kafka、Redis 和模型 SDK；领域层不依赖 HTTP。API 与 Worker 共享数据契约和领域逻辑，不通过相互 HTTP 调用耦合。同步客户端不得阻塞异步事件循环。

建议后续目录：`backend/`、`frontend/`、`infra/`、`docs/`、`tests/`。可以添加短 `AGENTS.md` 引用本文，但不要维护两份相互冲突的规范。

## 3. 唯一事实来源

| 组件 | 负责 | 不负责 |
|---|---|---|
| MySQL | 用户与授权、任务状态机、请求幂等、执行尝试、租约、重试、Outbox/Inbox、最终结果引用 | 大文件正文 |
| Kafka | 事件交付、分区、消费组、重放 | 当前任务状态、整个系统 exactly-once |
| MongoDB | 灵活的 Agent 步骤和结果文档、稳定 ID 去重 | 与 MySQL 一起裁决任务状态 |
| Redis | 有 TTL 的缓存、非关键进度、后续限流 | 唯一任务状态、唯一恢复依据 |
| 对象存储（后续） | 附件和生成文件 | 业务授权和任务状态 |
| 搜索（后续） | 可重建检索索引 | 原始资料唯一副本 |

查询任务的最终状态以 MySQL 为准。初版直接读取 MySQL，不要同时引入任务状态缓存。Redis 不可用时任务正确性不变；缓存使用 cache-aside、TTL、明确失效与降级策略，不承诺强一致。MongoDB 单文档原子性不等于跨 MySQL/MongoDB 原子事务。

## 4. 同步与异步时序

### 同步查询

浏览器 -> API 认证、资源级授权、参数校验 -> MySQL 任务状态 -> 根据已提交的结果引用读取 MongoDB -> 返回响应。不存在结果引用或尚未成功的任务，不呈现正式成功结果。每个资源请求均验证所有权，不只保护列表接口。

### 异步提交与执行

1. `POST /api/v1/tasks` 带 `Idempotency-Key`。同用户同键同请求摘要返回原任务；同键不同请求返回 409。用数据库唯一约束解决并发。
2. 同一个 MySQL 事务创建任务与 outbox 事件；事务成功后返回 202 和 task_id。禁止先发 Kafka 再写数据库。
3. relay 发送固定 event_id 的事件；Kafka 确认后才标记 outbox 已发送。确认与标记之间的宕机允许重复发送。
4. consumer 以 MySQL 事务插入唯一 inbox 记录并将对应任务标记为可执行；事务提交后才提交 Kafka offset。重投事件可安全忽略。按分区只提交已持久化的连续 offset，不能跨过尚未落库的早期消息。
5. executor 使用短事务领取 ready 任务，写入 attempt_id、递增 fencing token、租约到期时间；禁止将模型或网络调用放进数据库长事务。
6. 事务外执行 Agent。保存工具输入输出、动作和结果摘要，不记录或索要模型隐藏思维链。工具有超时、允许列表和执行预算；初版不提供任意 shell、任意文件路径或任意网络 URL 工具。
7. 将结果写入 MongoDB，采用稳定且 attempt 专属的 result_id；然后 MySQL 条件更新任务成功及结果引用，仅当前 fencing token、有效租约和运行状态允许提交。旧 attempt 不得覆盖新 attempt。
8. recovery 扫描过期租约，安排可恢复任务的新尝试。即使 Kafka offset 已提交，已落库任务仍可恢复。前端轮询真实 API；SSE 属后续增强，不是首版必需。

建议状态：`pending -> ready -> running -> succeeded`，运行失败进入 `retry_wait -> ready` 或终态 `failed`。每次合法转换在代码中集中声明并测试。取消只在实现独立语义后开放，不以删除记录模拟取消。

事件至少包含：`event_id`、`event_type`、`schema_version`、`task_id`、`occurred_at`、`trace_id`；按 task_id 分区。只携带必要数据，不放秘密或大结果正文。Kafka 顺序只在相关分区及具体消费策略内成立，不能宣称全局顺序。

## 5. 失败与一致性契约

- HTTP 响应丢失：重试同幂等键返回原任务；不重复创建。
- outbox 发布后未标记：重发同 event_id；Inbox 去重。relay 多实例时必须有领取租约或锁；首版可明确仅一实例。
- Inbox 已提交而 offset 未提交：重新消费不新增工作；禁止 offset 先于事务提交。
- Worker 执行中退出：租约恢复；fencing token 阻止旧执行器提交。不能仅设置 running 后永不回收。
- MongoDB 保存后 MySQL 更新前退出：允许孤儿文档；结果ID属于具体attempt，新attempt不复用旧attempt孤儿，因此仍可能再次调用模型。最终只暴露MySQL已提交引用的结果；孤儿清理未在本轮实现，也不能删除仍在执行的结果。
- 外部模型成功但网络响应丢失：可能再次调用和计费。若供应商提供幂等语义则按其文档使用，否则明确不能保证只调用一次。
- 重试区分永久/暂时错误；有限次指数退避与抖动，持久化 next_attempt_at；不得无限重试或在 Kafka consumer 内长时间 sleep。
- 超限失败在 MySQL 事务记录终态并写 DLQ outbox，随后发布死信事件。人工重放产生新事件并保留关联与审计，不通过随意重置消费组替代业务操作。
- 暂停 Redis 不影响任务成功或恢复；MongoDB 写失败不能标记 MySQL 成功；Kafka 停机时已创建任务保持 pending，恢复后 outbox 可继续发送。
- Kafka、MySQL、MongoDB、外部模型之间没有一个共同事务。只承诺显式实现的至少一次交付和幂等状态转移，不宣称端到端 exactly-once。

## 6. 分阶段实施与验收

每阶段先解释问题，再实现最小方案，再做正常和故障实验；未实现章节不得假装具备。

| 阶段 | 内容 | 验收 |
|---|---|---|
| 0 | 本文、架构/时序/状态机、技术选择记录 | 能解释组件职责与所有箭头 |
| 1 | React、FastAPI、MySQL；校验/错误码/分页/迁移/索引/事务/认证授权 | 真实 API 数据；迁移可重复执行；越权被拒；重启保留数据 |
| 2 | Worker、Kafka、Outbox/Inbox、幂等/租约/重试/DLQ | 重复投递安全；指定宕机点可恢复；Kafka 停机后可补发 |
| 3 | MongoDB 步骤结果、Redis 缓存进度 | Redis 清空不丢任务；MongoDB 失败不虚假成功 |
| 4 | 模型适配器、受限工具、超时和预算 | deterministic 模式明确标识；真实模型验收等待用户提供 API |
| 5 | 网关、对象存储、搜索、持久化调度、限流 | 每个可选组件有业务用途和故障实验 |
| 6 | JSON 日志、指标、OpenTelemetry | request/task/event/trace 标识串联；日志脱敏 |
| 7 | Compose、CI、Kubernetes、探针/资源/配置/迁移Job | 干净环境重现；真集成测试；部署教程有已执行/未执行证据 |

阶段 1 实现注册、登录、退出和当前用户，不透明 session cookie 与 CSRF；所有任务访问执行资源级授权。公开部署前需要完整认证与授权评审。初版部署默认只绑定本地/开发访问，不默认公开数据库端口。

传统后端课程还应覆盖连接池、慢查询与 EXPLAIN、唯一/复合索引、事务隔离、死锁重试、备份恢复、超时、背压、输入大小限制和安全边界。优先对应真实业务问题，不为了清单强行引入第二个消息队列、第二个关系库、服务网格、CDC 平台或分布式事务框架。

对象存储、搜索、调度等是后续课程，不是第一轮必须实现的生产平台。搜索索引可重建；调度入队也须幂等。Kubernetes 是部署层，不能解决业务幂等或跨库一致性。

## 7. 前端与 API 契约

前端至少展示任务创建、列表、状态、步骤和结果、错误/重试信息；状态来自 API，不使用倒计时假装完成。区分加载、空状态、依赖不可用、失败和成功。防止重复点击并保留后端幂等。刷新后能查询已有任务，不把浏览器内存当数据库。

统一前缀 `/api/v1`；请求/响应使用明确 schema。当前创建任务 DTO 使用 `id`（不是 `task_id`），并包含 `status`、`created_at` 等字段；任务详情包含 `attempt_count`、可展示错误与结果引用状态。列表有有界分页。OpenAPI 是后端接口源，前后端实现前先对齐字段；修改接口同步测试与示例。

## 8. 工程、测试与资源预算

- 容器镜像和依赖选择受支持版本并锁定，不能使用不受控 latest 作为可复现依据。迁移工具管理 schema，不依赖每次启动自动建表冒充迁移。
- 起步单 API 进程、单 Worker、低并发。Kafka 使用官方单节点开发配置，不新增 ZooKeeper；单节点不等于高可用。
- Compose 默认只启动该阶段真正需要的服务；后续 core 才包含全部四种基础设施。search/observability/storage/admin-tools 使用可选 profiles。
- 不默认同时启动 Kubernetes 与全套 Compose，不默认下载本地大模型。实测 profile 的空闲/负载内存、CPU、磁盘和启动耗时后给配置建议，不虚构最低内存承诺。
- 日后 Windows 指引应说明 WSL2 Linux 文件系统挂载与资源预算；不能擅自修改用户电脑。
- 单元测试覆盖状态机、幂等、重试分类和错误映射；真集成测试使用真实 MySQL/Kafka/MongoDB/Redis，而不是全部 mock。
- 至少覆盖：并发重复请求、重复 Kafka 事件、outbox 窗口宕机、Inbox/offset 窗口宕机、执行租约过期、旧 token 提交被拒、MongoDB 失败、Redis 停机、Kafka 恢复补发、越权读取。
- 区分已运行通过、失败、未运行和环境阻塞。Docker 不可用或网络拉取失败必须报告准确阻塞，不能用模拟测试冒充 Compose 成功。
- CI 至少静态检查、前端构建、后端测试；真实集成与故障实验可独立 job，但必须在验收记录中明确其执行状态。
- README 后续应提供：架构图、启动/停止/重置命令、阶段导航、数据流、故障演练、配置表和验收证据。删除数据卷是破坏性重置，应显式提示，不放进普通停止命令。

## 9. 公共仓库与安全

`.env`、密钥、数据库卷、构建输出和私有输入均不提交。`.env.example` 只含占位符与变量说明。日志不记录 Authorization、完整模型请求中的私密资料或工具秘密。错误响应不泄漏堆栈和连接字符串。对象存储路径及下载权限必须受控；Agent 工具默认最小权限。发布前检查暂存区和仓库历史中的敏感内容；不得为完成发布绕过权限拒绝。

公开仓库的创建/推送由协调者按已授权范围执行；以远端目标 commit 和 CI 状态核验结果，不将“本地文件存在”描述为“已发布”。没有用户另行授权，不部署公网服务、购买服务或产生超出约定的模型费用。

## 10. 设计依据（官方文档，实施时重新核对选定版本）

- Kafka 交付与事务边界：https://kafka.apache.org/41/design/design/
- Kafka 开发快速开始：https://kafka.apache.org/41/getting-started/quickstart/
- MySQL 事务领取与 locking reads：https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html
- SQLAlchemy Session/事务：https://docs.sqlalchemy.org/en/20/orm/session_basics.html
- MongoDB 原子性：https://www.mongodb.com/docs/manual/core/write-operations-atomicity/
- Redis cache-aside：https://redis.io/docs/latest/develop/use-cases/cache-aside/
- Compose profiles：https://docs.docker.com/compose/how-tos/profiles/
- FastAPI 容器与进程：https://fastapi.tiangolo.com/deployment/docker/
- Docker/WSL2：https://docs.docker.com/desktop/features/wsl/best-practices/
- Kubernetes CronJob：https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/


## 11. 首轮执行与接口协调契约

完整字段、状态码与身份安全契约由后端负责人写入 `docs/API_CONTRACT.md` 并与前端、测试、基础设施共同冻结。本节只固定协调者已确认的集成入口，不另定义冲突 DTO。

- FastAPI 入口：`backend.app:app`；容器内部端口 `8000`，对用户的主入口端口 `8080`。
- Worker 入口：`python -m backend.worker`；迁移入口：`python -m backend.migrate`。
- `GET /healthz` 存活检查；`GET /readyz` 检查 SQL/Kafka/Mongo 实际可用性，Redis 可降级；`GET /metrics` 指标。存活检查不因外部依赖暂时不可用触发无效重启。
- `/api/v1/auth/register|login|logout|me`；不透明 session 使用 HttpOnly cookie；鉴权写操作要求 `X-CSRF-Token`，并按完整接口契约验证来源/会话和 CSRF。
- `/api/v1/tasks` 创建/列表；任务详情及 events/results 路径和响应字段以 `docs/API_CONTRACT.md` 为准。
- 创建任务仍须满足幂等键与参数摘要契约；每个任务读取、事件、结果和变更接口均验证资源所有权。
- 前端通过同源网关或开发代理访问 `/api/v1`，不得把服务端秘密写入构建产物。真实 session 与 CSRF 流程需前后端集成验收。
- `deterministic` 与 `live` 模型模式必须在接口和界面明确区分；接口未实现不得用假数据冒充。

本地编写环境与 CI runner 的能力必须分别核验。已有 GitHub Actions 真实 Compose 集成和浏览器证据；当前工作流没有 Kind 集群验收 job，因此不能由 Compose 成功推断 Kubernetes 通过。每次报告均须绑定具体远端提交和执行结果。
