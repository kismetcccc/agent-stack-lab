# 后端模块功能契约：从代码、数据到故障交接

本页回答“**每个后端模块到底完成什么，出了问题交给谁，现有测试证明到哪里**”。宏观选型与架构图见 [ARCHITECTURE.md](ARCHITECTURE.md)，字段与 HTTP 状态码以 [API_CONTRACT.md](API_CONTRACT.md) 为准；本页不另定义一套 API，也不把后续组件写成已实现功能。

核对基线：`f36523fa` 的代码与 [CI 运行](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39725461902)。其 JUnit 记录为 **145 项后端/采集器测试、13 项真实组件集成、30 项浏览器测试，均无失败或跳过**。本次文档核对也在无 Docker 的环境重跑了前 145 项及 Ruff，全部通过；没有在该环境重新运行 Compose。测试数量不是功能保证，后面的对应关系和未验证边界更重要。

## 1. 先分清“模块”“进程”和“存储”

| 模块 | 代码入口 | 输入 → 输出 | 权威数据/依赖 |
|---|---|---|---|
| HTTP 契约与错误处理 | [app.py](../backend/app.py) `create_app`、`context` | HTTP → 校验后的调用、DTO 或安全错误 | 不自己保存任务状态 |
| 身份与会话 | [auth.py](../backend/auth.py) `Auth` | 凭据/cookie/CSRF → 用户身份 | SQL `users`、`sessions` |
| 任务应用服务与状态机 | [service.py](../backend/service.py) `TaskService`；[domain.py](../backend/domain.py) | 用户请求/执行事件 → 合法状态转换 | SQL `tasks`、`task_events`、`attempts` |
| 消息发送 | `TaskService.emit`、`relay_once`；[adapters.py](../backend/adapters.py) `KafkaBus` | SQL Outbox → Kafka 确认 → `sent_at` | SQL 记录待发义务；Kafka 交付 |
| 消息接收 | [worker.py](../backend/worker.py) `main`；`TaskService.receive` | Kafka 消息 → Inbox 和 ready → offset 提交 | SQL Inbox 是已接收凭据 |
| 执行与恢复 | `TaskService.claim`、`execute_once`、`finalize`、`recover` | ready/过期任务 → 尝试、结果引用或重试/失败 | SQL 租约、fence、`next_attempt_at` |
| 结果文档 | `MongoDocuments`；`TaskService.document` | attempt 结果 → 不覆盖的文档；已提交引用 → 结果 | MongoDB 内容，SQL 决定可见性 |
| 可丢弃缓存 | `ProgressCache` | 阶段提示/结果引用 → TTL 缓存 | Redis 不是权威 |
| 受限单 Agent | [agent.py](../backend/agent.py)、[agent_tools.py](../backend/agent_tools.py)、[agent_provider.py](../backend/agent_provider.py) | 唯一文本材料 → 有界只读工具动作和最终文本 | 不能自行提交 SQL 成功 |
| 装配、配置与迁移 | [runtime.py](../backend/runtime.py)、[config.py](../backend/config.py)、[migrate.py](../backend/migrate.py) | 可信进程配置 → 适配器/初始 schema | 真组件与测试替身明确分开 |
| 运维与测试辅助 | `app.py` 探针/指标；`worker.py` 心跳；[faults.py](../backend/faults.py) | 观测请求/显式测试开关 → 状态、指标或暂停 | 不是业务恢复的替代品 |

实际部署是 **API 进程 + Worker 进程 + 一次性迁移进程**。Worker 有 consumer 主线程、relay 线程和 executor 线程；`recover()` 在 executor 循环中先于 `execute_once()` 调用，**不是第四个独立线程或调度服务**。多个后端模块不等于多个 Agent。

## 2. 用一条具体任务串起所有契约

示例合成材料：`[search:销量] [stats] 材料：销量 10 20 30`。沿用[现有 curl 闭环](FAILURE_LABS.md#curl-后端闭环bash--wsl2无需前端)注册和提交，只替换 `prompt`；不需要模型 key。脚本控制器会读取材料、字面搜索，再按观察结果决定是否统计，不能把这个分支写成真实 LLM 推理。

| 步骤 | 发生的事实 | 此时失败由谁接手 |
|---|---|---|
| 1. 登录/注册 | SQL 保存密码哈希与随机会话/CSRF 摘要；HTTP 设置 HttpOnly cookie | 无有效身份就拒绝；不创建任务 |
| 2. 提交 | `submit` 检查身份、CSRF、幂等键；`create` 同一 SQL 事务写 task、Outbox 和 pending 事件 | 事务失败不接受；响应丢失可用原键重试 |
| 3. 返回 202 | 返回的任务字段是 `id`，状态通常为 `pending`；不是已经完成 | 用户用该 id 查询，不等待同一 HTTP 请求完成执行 |
| 4. relay 发布 | 固定 `event_id`，以 `task_id` 为 Kafka key；确认后写 `sent_at` | 发送失败仍留 Outbox；确认后落库前退出可重复发布 |
| 5. consumer 接收 | 同一 SQL 事务写 Inbox，并将 pending 改 ready；提交后才同步提交 offset | offset 丢失导致重投，由 Inbox 唯一约束去重 |
| 6. executor 领取 | 短事务把 ready 改 running，递增 fence/attempt_count，生成 attempt_id 和租约 | 进程失联后由 recovery 检查租约，而不是再等 Kafka |
| 7. 执行 | SQL 事务外调用 `Model.run` → `run_agent` → 三个只读工具 | 永久错误终止；可重试错误记录 retry_wait |
| 8. 保存结果 | Mongo 文档 ID 为 `task_id:attempt_id`，先写文档再提交 SQL 引用 | Mongo 失败不能成功；中间退出允许产生不可见孤儿文档 |
| 9. 正式完成 | `finalize` 同时检查 running、相同 fence 和未过期租约，然后提交 succeeded/结果引用/Attempt | 过期或旧执行器返回 false，不能覆盖新尝试 |
| 10. 查询结果 | 每次先 SQL 校验 owner 和成功引用，再 Redis 命中或回源 Mongo | Redis 故障降级；SQL 授权故障不能靠缓存绕过；Mongo 回源失败返回 503 |

状态机仅有：

```text
pending → ready → running → succeeded
                      └→ retry_wait → ready
                      └→ failed
```

`failed` 和 `succeeded` 是终态；没有取消、手工重试或删除接口。`progress` 是由状态映射得到的阶段提示（例如 running 为 30），**不是模型真实完成百分比，也不是从 Redis 读出的执行进度**。

## 3. HTTP 与身份：先决定“能不能做”，再进入业务

### 3.1 HTTP 边界

- **为什么存在**：把外部输入、状态码、错误信封与内部业务分开，路由不直接拼 Kafka/Mongo/Redis 操作。
- **输入/输出**：`Credentials`、`TaskInput` 与 header/cookie 输入；成功返回任务/列表/结果 DTO，失败返回 `error` 和 `request_id`。`context` 生成 `X-Request-ID`，对请求流和声明长度都实行 65,536 字节上限；prompt 长度 1..10,000，trim 后不允许纯空白。任务列表 `limit` 为 1..100、`offset` 为 0..1,000,000。
- **成功/失败**：提交 202 只表示 SQL 已接受；同键不同请求 409；未登录 401；CSRF 或 Origin 不符 403；不可见任务 404；输入校验 422；SQL 不可用 503；未知异常统一 500，不返回堆栈或连接串。
- **安全边界**：写请求如果携带 Origin，必须与 `APP_ORIGIN` 精确一致；没有 Origin 的非浏览器客户端仍须满足会话/CSRF。同步路由使用同步适配器，不把驱动调用堆进 async 业务路由。当前没有全局限流、请求入队背压或公网防滥用保证。
- **不负责**：不会因返回 202 就保证任务必定成功；也不以 `/readyz` 结果代替每条请求的实际检查。
- **学习实验**：沿 curl 闭环观察 202 与随后 succeeded 的区别，再阅读 `test_validation_envelopes_and_chunked_body_limit`。不要发真实私密文本做教学样例。

### 3.2 会话、CSRF 与资源所有权

- **入口与事实来源**：`Auth.login/identity/refresh/logout`；SQL 保存 `users` 与 `sessions`。用户名转小写，密码使用带随机盐的 scrypt；随机 session token 和 CSRF token 只保存 SHA-256 摘要。不存在的帐号也执行密码验证工作，不把“耗时相同”扩大为完整侧信道安全证明。
- **输出**：登录/注册返回用户与 CSRF token；cookie 为 HttpOnly、SameSite=Strict，Secure 由 `COOKIE_SECURE` 控制，默认本地 HTTP 不启用。会话有效期 86,400 秒。
- **调用顺序**：写任务/退出先 `identity(write=True)`；所有详情、events、attempts、agent-steps、results 都再次通过 `owned(owner, task_id)`。缓存命中也不能跳过该授权。
- **失败行为**：过期/不存在会话 401；跨用户与不存在任务统一 404。`GET /auth/me` 会轮换 CSRF，后续写操作必须使用新 token；旧 token 被拒绝。退出从 SQL 删除当前会话并清 cookie。
- **不负责**：无 MFA、找回密码、邮件验证、账号管理或会话清理任务；没有声称经过完整公网认证审计。
- **学习实验**：按 curl 示例退出后读取任务，观察 401；用第二个合成帐号读第一个的任务，观察 404。测试入口见第 6 节，不公开 cookie/CSRF。

## 4. SQL、消息与执行：用小事务传递责任

### 4.1 任务账本与幂等

- **入口**：`TaskService.create/same/owned/listing`；[db.py](../backend/db.py) 中的 `Task`、`Outbox`、`Inbox`、`Attempt`、`TaskEvent`；`domain.transition` 集中拒绝非法转换。
- **事实来源**：owner、任务状态、重试时间、租约、fence 和正式结果引用都在 SQL。`(owner_id, idempotency_key)` 唯一约束决定并发赢家，不能只依赖提交前查询。
- **输入/输出**：原始幂等键先做摘要，避免 MySQL 排序规则和尾空格改变其不透明语义；请求摘要来自经过 API 验证/trim 的 prompt。同用户同键同摘要返回原任务，不同摘要 409。不同用户的键互不冲突。
- **失败边界**：任务、Outbox、pending 生命周期事件在一个事务提交；并发插入失败后回滚，再查已提交赢家。SQL 不可用不能退到 Redis 创建或授权任务。
- **查询边界**：`events` 为 SQL 生命周期记录，不是工具动作；`attempts` 为尝试记录。两者最多返回 100 项，当前没有各自的游标分页；events 的 sequence 是返回时按时间/id 排序生成，不是全局消息序号。
- **学习实验**：重复原键原材料，再更换材料观察相同 id 与 409；阅读唯一约束和 `test_concurrent_idempotency_and_conflict`，说明“先查再插”为何仍会竞争。

#### 只读 SQL / EXPLAIN 小实验：索引服务于哪条查询

**仅用于独立、只有合成数据的教学数据库；本节 SQL 已按模型和查询代码核对，但没有在本次无 Docker 的文档环境执行，不附虚构执行计划。** 使用已安全配置的数据库客户端，不把密码写进命令参数或公开截图。把下面 `SYNTHETIC_OWNER_ID` 换成自己的合成帐号 ID；不查询用户密码/会话表，也不执行 UPDATE、删表或领取任务。

| 实际表/索引 | 对应的代码查询 | 需要观察的边界 |
|---|---|---|
| `tasks` 主键 `id`；唯一约束 `(owner_id, idempotency_key)` | `owned/get/finalize`；`create/same` | 唯一约束保证同用户幂等键不重复；源码未显式命名该唯一索引，用 `SHOW INDEX` 看实际数据库名字，不猜名字 |
| `tasks.ix_task_owner_created (owner_id, created_at)` | `listing`：owner 过滤，created_at/id 降序分页 | 排序和 LIMIT 是实际查询的一部分；OFFSET 增大不能自动保持相同成本 |
| `tasks.ix_task_queue (status, next_attempt_at)` | `recover`：retry_wait 且到期；`claim`：ready | claim 按 created_at 排序，而该索引第二列为 next_attempt_at；**存在队列索引不等于完全覆盖领取排序**。租约扫描用 lease_until，也不是该索引的第二列 |
| `outbox.ix_outbox_sent_at (sent_at)` | `relay_once`：`sent_at IS NULL LIMIT 50` | 支持寻找待发记录；不是多 relay 锁/领取协议 |
| `inbox` 主键 `event_id` | `receive` 插入与重复检查 | 去重靠唯一性，不靠应用先查询 |
| `attempts.ix_attempts_task_id (task_id)`；`task_events.ix_event_task_time (task_id, created_at)` | `attempts`、`events` 的 task_id 过滤与时间排序 | 尝试索引没有 started_at 列；事件还按 id 破除同时间排序，不能把两种查询说成同一计划 |

```sql
-- 已连接教学数据库 agentlab 后执行；这些语句不返回 prompt 或身份秘密。
SHOW INDEX FROM tasks;
SHOW INDEX FROM outbox;
SHOW INDEX FROM attempts;
SHOW INDEX FROM task_events;

-- 对应 TaskService.listing 的过滤/排序/分页；投影缩小为无正文元数据。
EXPLAIN SELECT id, status, created_at
FROM tasks
WHERE owner_id = 'SYNTHETIC_OWNER_ID'
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 0;

-- 对应 claim 的候选选择；故意不执行 FOR UPDATE / SKIP LOCKED 或状态更新。
EXPLAIN SELECT id, created_at
FROM tasks
WHERE status = 'ready'
ORDER BY created_at
LIMIT 1;

-- 对应 recover 的到期重试筛选；实际代码使用应用当前时间作绑定参数。
EXPLAIN SELECT id, next_attempt_at
FROM tasks
WHERE status = 'retry_wait' AND next_attempt_at <= UNIX_TIMESTAMP()
LIMIT 100;
```

先比较 `possible_keys`、实际 `key`、估计 `rows` 与 `Extra`，再回到索引列顺序解释差异。`EXPLAIN` 是诊断，不保证一定选择某索引；数据量、分布和统计信息会影响计划。这里为避免正文暴露缩小了投影，可能改变覆盖索引条件，**不能把示例计划当作 ORM 原查询的性能实测**；空教学表的计划也不能代表真实负载。此处使用普通 EXPLAIN，不是会实际执行查询的 EXPLAIN ANALYZE；没有获取执行锁或证明并发领取正确性。

连接行为也要一起读：[db.py](../backend/db.py) `connect` 开启 `pool_pre_ping`；MySQL 驱动连接超时 3 秒、读/写超时各 5 秒，池大小等参数未在本项目显式调优。连接检查不保证一个事务运行期间数据库永不掉线，也不是事务自动重试。SQL 故障由 API 映射为 503，Worker 由现有循环/持久状态接手；停库恢复与连接池容量仍应分别实测。

### 4.2 Outbox relay 与 Kafka 适配器

- **职责**：`emit` 在调用方事务记录发送义务；`relay_once` 每轮取最多 50 条未发送事件；`KafkaBus.publish` 等待 broker 确认后才允许写 `sent_at`。
- **输入/输出**：事件只包含 event_id、event_type、schema_version、task_id、occurred_at、trace_id；不带 prompt、会话或结果正文。`task.created` 发任务 topic；终态 `task.failed` 发 DLQ topic。
- **成功/重试**：Kafka producer 开启幂等，delivery timeout 10 秒，flush 等待最多 12 秒；未确认抛暂时错误。relay 线程记录异常类型后继续轮询，SQL Outbox 保留发送义务。
- **一致性边界**：确认和 `sent_at` 不在共同事务中，允许同 event_id 再发。producer 幂等不等于端到端 exactly-once，也不保证外部模型只调用一次。
- **部署/安全边界**：当前只运行一个 relay/Worker，没有多 relay 的领取租约。开发 topic 为单分区、单副本；Kafka 内网 PLAINTEXT，无认证，不映射主机端口。不能直接当作公网或高可用部署。
- **学习实验**：在独立开发栈运行现有 `scripts/test-integration.sh` 的 Kafka 停机/恢复阶段，观察 pending、未发送 Outbox、恢复后结果；不要把失败事件进入 Outbox 和 Kafka 已接收 DLQ 混为一谈。

### 4.3 Inbox 与 consumer

- **职责**：consumer 只负责把交付变成持久可执行工作，不在 poll 中运行模型。`receive` 校验 schema_version=1、event_type=task.created，然后事务内插入唯一 Inbox、锁任务并将 pending 改 ready。
- **输入/输出**：新事件返回 true；已持久化同 event_id 返回 false，但都是可安全确认的交付。已有 ready/running/终态任务不会被重复事件退回 pending/ready。
- **offset 契约**：`enable.auto.commit` 和 `enable.auto.offset.store` 都关闭；逐条持久化成功后同步 `consumer.commit(message=...)`。持久化或提交失败会退出消费循环，而不是继续跨过尚未落库的消息。
- **失败边界**：未知 schema/type、未知任务或不能解析的消息不会被静默跳过；主循环异常退出，Compose 配置可重启进程。**当前没有坏消息隔离/人工跳过工具**，持续坏消息可能反复阻塞消费，不能宣称自动修复任意消息污染。
- **安全边界**：内部 Kafka 事件不是用户授权凭据；用户查询仍必须走 API 的 owner 检查。生产者访问控制和受审计重放尚未实现。
- **学习实验**：阅读 `test_full_chain_and_duplicate_event` 中真实重投与 Inbox/Attempt 数量断言，再读 `test_replay_ack_gap_and_expired_lease_fencing`；说明为何 offset 已提交也不意味着 Agent 已成功。

### 4.4 executor、租约、重试与 recovery

- **职责与顺序**：`claim` 用短事务和 `FOR UPDATE SKIP LOCKED` 领取最早 ready 任务；递增 fence/attempt_count，创建 attempt，默认租约 120 秒。事务外执行和写 Mongo，再由 `finalize` 重新锁行验证提交条件。
- **成功条件**：必须仍为 running、fence 相同且租约未到期。Mongo 已有当前 attempt 的文档时可读取，但新 attempt 有新 ID，不能复用旧尝试的孤儿文档冒充新成功。
- **失败分类**：`PermanentError` 及工具/协议/预算/配置/拒绝类 Agent 错误直接 failed；其余执行异常有限重试，保存安全错误码而非原始异常消息。默认最多 3 次尝试，包含第一次，不是“额外重试 3 次”。
- **重试交接**：`fail_locked` 持久化 `next_attempt_at = now + min(60, 2**attempt_count) + [0,1)` 秒；不在 Kafka consumer 内 sleep。`recover` 每轮最多检查 100 个过期 running 和 100 个已到期 retry_wait；前者转重试/失败，后者直接 ready，**重试不重新经过 Kafka**。
- **终态失败**：与 failed 状态一起写 `task.failed` Outbox；relay 随后发送 DLQ。没有“点击重试”或消费组重置式的业务重放实现。
- **明确限制**：没有自动续租、并发执行池或精确到点的独立恢复定时器；恢复间隔受 executor 当前执行耗时影响。fence 保护正式提交，不阻止所有重复计算或供应商重复计费。
- **学习实验**：用现有 recovery 集成测试观察过期 attempt、递增 fence 和旧提交被拒绝；不要把人为修改租约/直接调用服务方法的实验描述为完整双进程竞态验证。

## 5. 结果、缓存和 Agent：内容与完成状态不能混淆

### 5.1 MongoDB 结果文档

- **为什么独立**：适合存储最终文本、模式标签和不同形状的工具动作；不承担权限、队列或任务状态机。
- **入口/输出**：`MongoDocuments.save/get` 写读 `agent_lab.results`；`_id=task_id:attempt_id`，`$setOnInsert` 使适配器重复保存不覆盖已存在内容。这是应用写法，不是数据库强制禁止管理员修改文档。
- **正式可见条件**：`TaskService.document` 先确认 SQL owner、succeeded 和非空 result_id，再读取该引用。非成功结果返回 409；`agent-steps` 在未提交时返回空 items、`availability=not_committed`。
- **失败/兼容**：Mongo 写失败不能提交 SQL 成功；写后 SQL 提交前失败可能留下孤儿。成功任务回源文档不可读时返回 503，不更改 SQL 成功状态。旧文档明确标为 `legacy_single_call`，不制造 Agent 工具轨迹；错误的模式元数据不能伪装 legacy。
- **不负责**：没有孤儿清理、失败尝试完整工具审计、实时步骤流、对象文件存储或跨 SQL/Mongo 事务。
- **学习实验**：观察 `test_legacy_document_read_is_truthful_and_never_rewritten`；在故障脚本中先删除测试结果缓存、再停 Mongo，才能证明回源失败。缓存 hit 时成功返回并不能证明 Mongo 在线。

**文档形状与响应形状分开看**：当前持久文档包含 `_id`、task_id、attempt_id、content、model_mode、execution_kind、controller_mode、steps；其中 `_id` 由 Mongo 适配器写入，其他内容来自 `run_agent`。历史文档可有同样的任务/尝试/文本/steps 基础字段，但缺少 execution_kind 与 controller_mode；测试中的旧 `summary` 步骤不会转换成新工具动作。具体新结果/工具响应示例及 legacy 映射统一见 [API 契约“受限单 Agent：具体响应契约”](API_CONTRACT.md#受限单-agent具体响应契约)，存储兼容样例见 [test_single_agent.py](../tests/integration/test_single_agent.py) `test_legacy_document_read_is_truthful_and_never_rewritten`。`cache_status` 和 `availability` 是读取 API 生成的字段，不是 Mongo 文档的任务完成权威。

### 5.2 Redis cache-aside 与阶段提示

- **入口**：`ProgressCache.write/read_result/store_result`。配置为空时 disabled；网络超时各 1 秒，异常被降级处理，不改变 SQL 状态。
- **两种数据**：`progress:<task_id>` 目前只在领取后写 `running`，TTL 300 秒；并不是完整状态同步，成功后短时间仍可能看到这个提示。`result:<result_id>` 是不可变结果缓存，同样 TTL 300 秒。
- **读取顺序**：SQL 所有权和成功引用 → Redis → 未命中时 Mongo → 尽力写 Redis。结果 API 报告 `hit/miss/unavailable/disabled`；它描述读取阶段，后续缓存写失败不会自动把 miss 改成 unavailable。
- **降级与安全**：Redis 停机、损坏 JSON 或缺失都可回源；缓存完全不能绕过 SQL 授权。Mongo 不可用时已有有效缓存可返回，但 cache miss 应 503。客户端没有直接访问 Redis 的入口。
- **不负责**：没有分布式锁、任务恢复、限流或可变业务对象缓存失效；AOF 开启不把它变成任务权威。
- **学习实验**：同一成功任务连续读 results，再停 Redis；观察 miss/hit/unavailable 与 SQL 状态不变。首次读取也可能已 hit，不要把“一定先 miss”写死在手工实验结论里。

### 5.3 模型选择、控制器与只读工具

- **入口分工**：`Model.run` 检查任务创建时模式与当前 Worker 模式一致，选择 `ScriptedController` 或 `LiveController`；`run_agent` 控制预算、工具调用与最终结果，`agent_types.py` 的 `Final/ToolCall` 是内部决策契约。
- **默认功能**：deterministic 明确输出 `scripted_test`，根据 `[search:...]`、`[stats]` 等测试标记和观察分支运行。它验证调用链，不提供任意自然语言理解保证。详情见 [SINGLE_AGENT.md](SINGLE_AGENT.md) 和 [逐步导读](AGENT_WALKTHROUGH.md)。
- **唯一材料**：prompt 就是本任务的 task_input；`read_text` 按字符偏移读取，`search_text` 做字面搜索，`numeric_stats` 做有范围限制的 ASCII 十进制词法统计。工具参数不接受额外键，布尔值不能冒充整数；统计结果用十进制字符串，不假装金融/表达式解析。
- **硬预算**：最多 6 次决策、5 次工具；执行时间最多 60 秒且再受“租约剩余时间减 15 秒”限制。单次参数 2 KiB、单次工具输出 4 KiB、累计工具输出 16 KiB、最终文本 8 KiB；工具返回分页/截断信息，不悄悄补全未读材料。
- **live 边界**：必须 `MODEL_MODE=live`、显式允许 live，并有私密 key、model name 和合法 HTTPS base URL。传输禁止重定向，request/response 各限 64 KiB；429/5xx/传输错误归暂时失败，协议不兼容/拒绝/预算错误不伪造成功。适配器内部不自行重试，持久重试归 TaskService。
- **安全/不负责**：只允许三个纯文本工具，无 shell、任意文件、URL 抓取、外部副作用、多 Agent 或长期记忆。供应商隐藏推理及伴随工具调用的辅助文本被丢弃，保存公开动作/观察/最终文本，不保存隐藏思维链。工具输入输出仍可能含用户材料，不能直接上传公共日志。
- **证据边界**：provider 单元测试使用可控 HTTP transport，不是真实供应商网络；默认 CI 为脚本模式。任何独立的真实 provider 小样本也不等于完整 API→Kafka→Worker→结果→界面的 live 验收，更不等于通用模型能力评测。
- **学习实验**：先运行工具/provider 单元测试，再用本页合成材料走完整默认链路；没有显式授权与私密配置时不要为学习实验启用真实模型。

## 6. 可运行的功能—测试对应表

下表的测试名称均存在于仓库。单元测试的 SQLite/MemoryBus/MemoryDocuments 只证明代码分支，**不能证明 MySQL 行锁、Kafka offset 或 Mongo/Redis 网络行为**。

| 功能 | 快速代码测试 | 真实组件证据 / 未证明部分 |
|---|---|---|
| 会话、CSRF、owner、错误信封 | [test_core.py](../backend/tests/test_core.py) `test_auth_idempotency_and_ownership`、`test_chunked_body_limit`、`test_unexpected_error_sanitized_and_traced` | [test_api_contract.py](../tests/integration/test_api_contract.py)、[test_chain.py](../tests/integration/test_chain.py) 的 auth/expiration/pagination；非公网安全审计 |
| 同键并发与大小写/空格语义 | `test_same_owner_idempotency_concurrent`、`test_opaque_keys_preserve_case_and_space` | `test_concurrent_idempotency_and_conflict`、`test_idempotency_keys_are_byte_exact_not_mysql_collation`；未证明任意负载容量 |
| Outbox/Inbox 与重复事件 | `test_pipeline_duplicate_inbox_and_result`、`test_outbox_ack_window_republish_stable_id` | `test_full_chain_and_duplicate_event`、recovery 测试；确认窗口由受控状态/调用构造，不是所有窗口真实 SIGKILL |
| 租约、fence、有限重试、DLQ | `test_expiry_fence_and_bounded_retry`、`test_transient_retry_budget_and_dlq`、`test_permanent_failure_dlq` | [test_recovery.py](../tests/integration/test_recovery.py) 两项，真实存储及 DLQ 消费；不是多 Worker 扩容验收 |
| Mongo 先持久化、只公开已提交动作 | `test_document_failure_never_success`；[test_agent.py](../backend/tests/test_agent.py) 的 steps/legacy/metadata 测试 | [test_single_agent.py](../tests/integration/test_single_agent.py)、recovery 旧 fence 文档检查；未覆盖孤儿清理 |
| Redis 可丢弃、TTL 与回源 | `test_cache_aside_and_outage` | `test_full_chain_and_duplicate_event` 及 [outage_probe.py](../tests/integration/outage_probe.py)；无缓存命中率/压测结论 |
| Agent 工具、预算和模式 | [test_agent.py](../backend/tests/test_agent.py)、[test_agent_tools.py](../backend/tests/unit/test_agent_tools.py)、[test_agent_provider.py](../backend/tests/unit/test_agent_provider.py) | 真实组件集成验证 scripted 工具动作持久化；live 全链路未在默认 CI 验收 |
| 初始迁移、健康和配置 | `test_migration_repeat_and_sqlite_guard`、`test_validation_origin_readiness`、`test_username_normalization_and_invalid_config` | Compose migrate→API/Worker；不证明已有数据库 schema 升级/回滚、备份恢复或 Kubernetes |

**复现入口**（在仓库根目录；按 README 先准备锁定依赖）：

```bash
# 与 CI 同类的离线功能回归；不启动外部服务，不调用真实 provider。
uv run pytest backend/tests tests/judge/test_capture.py -m 'not integration'
uv run ruff check backend tests/judge

# 单独读一个模块时缩小测试范围，仍然不是“真实集成通过”。
uv run pytest backend/tests/test_core.py
uv run pytest backend/tests/test_agent.py backend/tests/unit

# 需要已运行的独立 Compose 开发栈；会停止/恢复服务，并生成合成用户与任务。
bash scripts/test-integration.sh
```

真实集成脚本先跑 11 项正常链路/API/Agent 测试，再独占 Worker 执行 2 项恢复测试，并另跑 Redis/Kafka/Mongo 停机和 Worker 重建探针。**这些脚本阶段不全部体现在“13”这个 JUnit 数字中**；应同时核对 CI 步骤和恢复日志。前端的单元、浏览器证据独立，不拿 UI 截图替代后端断言。

`scripts/test-crash-windows.sh` 是可选且未验收的精确 SIGKILL 实验，当前不在必过 CI 内；不能因为有脚本就称四个宕机窗口均已实跑，已知问题见第 8 节。

## 7. 配置、迁移、部署与观测的实际能力

### 7.1 Runtime 和 schema

`Runtime` 将业务与适配器接起来：`LAB_MODE=production` 选择真实 Kafka/Mongo，test/demo 选择内存替身；SQLite 在 production 明确拒绝。这个 mode 名称只描述适配器，**不是生产就绪认证**。Redis 是否启用独立由 URL 决定。API 不自动建表；Compose 的单次 `python -m backend.migrate` 完成后才启动 API/Worker。

当前迁移是 v1 初始 `create_all` 与版本记录，可重复执行初始建表，**不能升级已存在的表结构**。新增列/索引时必须增加真正的版本迁移和已有数据升级测试，不能修改模型后重跑 create_all 就宣称完成升级。

默认 Compose 只启动 MySQL、Kafka、Mongo、Redis、migrate、API、Worker；数据服务不发布主机端口，API 只绑定本机 8080。UI/Nginx 为显式覆盖配置，见 [UI_GUIDE.md](UI_GUIDE.md)。数据卷分开持久化，普通 `docker compose down` 保留数据；删卷不是停止或故障恢复方法。镜像 tag 和依赖锁定支持复现，但不等于漏洞/支持周期审计或 digest 不可变保证。

### 7.2 探针、指标和日志应当如何解读

| 观察入口 | 实际检查/输出 | 不能据此推断 |
|---|---|---|
| `GET /healthz` | API 进程返回 ok，不访问外部依赖 | 四组件在线、任务能成功 |
| `GET /readyz` | SQL schema_version=1 可读、Mongo ping、Kafka broker 元数据；test/demo 明示替身 | **不探测或列出 Redis**；不检查 live 凭据/供应商和 Worker 执行能力 |
| `GET /metrics` | `lab_http_requests_total`、`lab_http_request_duration_seconds` 及客户端默认指标；route 用模板避免 task UUID 高基数 | 没有任务成功率、Outbox 积压、重试数、租约过期数、完整 tracing |
| `python -m backend.worker --healthcheck` | consumer 主循环写出的 heartbeat 文件是否小于 30 秒 | 不单独验证 executor/relay/recovery 工作进度，不能当全部模块健康证明 |
| `GET .../events`、`.../attempts` | SQL 生命周期、组件名、trace_id 与尝试结果 | 不等于跨服务 OpenTelemetry spans，也不包含失败尝试完整工具步骤 |
| API/Worker 错误日志 | API 未知异常记录 request_id/异常类型；Worker loop 记录失败类型，避免原始秘密消息 | 不是完整结构化 JSON 业务审计或现成告警平台 |

`/readyz` 失败不会在代码中自动拒绝所有业务请求；是否摘除流量是部署入口的责任。Compose health 状态也不自动等于重启：Worker 主循环异常退出与“容器仅 unhealthy”是两件事。Redis 可降级的证据来自结果 cache_status 和故障测试，不是当前 readiness 的 degraded 字段。

故障钩子 `pause_at` 只读显式进程环境开关，没有 HTTP 触发接口，默认关闭。它是测试辅助，不是业务调度器；普通启动不加载 `compose.fault-test.yaml`。

### 7.3 明确未实现或延期

- Kubernetes 清单与脚本仅供后续部署学习，未获本轮真实集群验收；离线 YAML 校验不证明调度、PVC、NetworkPolicy 生效。
- 多 Worker/relay 扩容、租约续期、DLQ 管理/审计重放、取消、失败尝试完整轨迹、孤儿文档清理、备份恢复和容量/HA/SLA 尚未实现验收。
- 限流、对象存储、检索/RAG、外部搜索、持久化定时调度、多 Agent、完整 Prometheus/Grafana/OTel 链路继续按实际业务需要分阶段安排，不为组件清单增加服务。
- 默认 scripted 的完整主链路已验证，不把它包装为真实 LLM 或通用 Agent 智能评测。

## 8. 代码核对发现的优先改进点

以下是本次审计基线的缺口，不是已修复声明。实施与验收状态统一在 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 更新，避免本页维护第二份任务板。

| 优先项 | 现状与可复核依据 | 最小修复 / 验收目标 |
|---|---|---|
| **先修：安全补齐开发配置** | [infra-init-env.py](../scripts/infra-init-env.py) 用 `O_EXCL`，任意已存在 `.env` 都直接退出；先写模型变量的学习者无法补齐 Compose 必需的四个数据库密码。无需读取任何真实秘密即可用独立临时文件复现 | 显式补缺模式，只生成缺失项，不覆盖既有值；处理空值、重复键、符号链接和权限，保持输出脱敏；隔离临时目录测试新建、幂等、保留、拒绝路径。不能建议用户删除已有凭据来消除错误 |
| **其次：修复可选精确宕机实验** | [compose.fault-test.yaml](../compose.fault-test.yaml) 租约为 3 秒，但 `run_agent` 强制留 15 秒，因此到不了正常 `after_mongo_save`；纯代码复现立即 `AgentBudgetError`。`LAB_TEST_TASK_ID` 虽被传入，`faults.py` 未使用，暂停没有目标任务隔离 | 将真实 task_id 贯穿并匹配 hook；采用足够执行预算的租约和受控恢复时序，处理 marker 生命周期；四个 SIGKILL 点分别在真实 Docker 中留下证据后，才能升级为已验收实验 |
| **随后：让 Worker 可观测性覆盖实际工作** | `worker.py` heartbeat 只随 consumer poll 更新；executor/relay 异常虽记录日志，主心跳仍可新鲜。`app.py` metrics 只有 HTTP 请求计数与时延 | 先定义独立的循环存活/最近成功/积压语义和脱敏指标，不能把“没任务”当故障；补 executor/relay 失效与空闲正常的测试，再考虑告警。不要在依赖短暂中断时无差别重启全部组件 |

学习验收的最低标准是：能指出代码入口、权威记录、一个正常例子、一个故障交接，以及测试没有证明什么。先保证这些主功能清楚、可复现，再增加细粒度评测或外围系统。
