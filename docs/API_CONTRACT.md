# API 契约：组件操作台与原任务接口

内部 API 端口 8000，默认宿主后端端口 8080，可选同源界面 8081。UI overlay 固定 `APP_ORIGIN=http://localhost:8081`。OpenAPI 由当前后端生成；本文与[冻结计划](COMPONENT_PLAYGROUND_PLAN.md)说明字段及边界，不代替真实运行验收。

## 组件操作台 `/api/v1/lab`

**HTTP API 仍为 v1；数据库迁移目标为 schema v2；Kafka 教学消息 envelope 的 `schema_version` 为 1。** 三者独立。以下接口不需要 task、Agent 或模型配置。

### 通用规则

- 全部要求有效登录，POST/PUT/DELETE 继续要求 `X-CSRF-Token` 和原 Origin 校验。**lab 数据由所有本地已登录账号共享**，不接受 owner/tenant，不按账号过滤；原 `/tasks` 所有权不变。
- JSON 拒绝未知字段、非法类型及非法 Unicode；TTL 不接受布尔值/小数，字符串不接受数字强制转换。全局实际请求流上限 64 KiB，另有组件预算。
- MySQL/Mongo ID 由服务端生成 UUIDv4；Kafka ID 由调用端发送前生成 UUIDv4。ID 路径非法为 422，合法但不存在为 404。
- 时间为 UTC ISO 8601；可空字段返回 `null`，不省略。`observed_at` 仅表示这次服务端观察。
- 三种列表返回 `{items,total,limit,offset}`：`limit` 默认 20、1..50；`offset` 默认 0、0..10000；按 `created_at DESC,id DESC`。并发写入时不是跨页一致性快照。
- PUT 完整替换可编辑字段，没有行版本/乐观锁；共享编辑后提交覆盖先提交。DELETE 必须 `?confirm=true`，没有批量删除。
- 响应有 `X-Request-ID`；错误 `{error:{code,message},request_id}` 不含连接串、堆栈或秘密。错误不能包装成空数据或成功。
- `LAB_MODE=test/demo` 明示替身，不作为真实集成证据；production 使用真实适配器且不静默回落内存。该 mode 名称不是生产安全认证。

### 路由

路径均以 `/api/v1/lab` 开头。

| 方法与路径 | 请求 | 成功响应 |
|---|---|---|
| POST `/mysql/records` | `{name,value}` | 201 MySQLRecord |
| GET `/mysql/records` | 分页 | 200 Page&lt;MySQLRecord&gt; |
| GET `/mysql/records/{id}` | UUIDv4 | 200 MySQLRecord |
| PUT `/mysql/records/{id}` | `{name,value}` | 200 MySQLRecord |
| DELETE `/mysql/records/{id}?confirm=true` | 无 body | 204；不存在为 404 |
| PUT `/redis/keys/{key}` | `{value,ttl_seconds}` | 200 RedisObservation |
| GET `/redis/keys/{key}` | 合法 key | 200 RedisObservation，包括不存在 |
| DELETE `/redis/keys/{key}?confirm=true` | 无 body | 204，包括已过期/不存在 |
| POST `/mongo/documents` | `{document:object}` | 201 MongoDocument |
| GET `/mongo/documents` | 分页 | 200 Page&lt;MongoDocument&gt; |
| GET `/mongo/documents/{id}` | UUIDv4 | 200 MongoDocument |
| PUT `/mongo/documents/{id}` | `{document:object}` | 200 MongoDocument |
| DELETE `/mongo/documents/{id}?confirm=true` | 无 body | 204；不存在为 404 |
| POST `/kafka/messages` | `{id,key,value}` | 首次 broker 确认 202；同 ID 同内容重查 200；KafkaMessage |
| GET `/kafka/messages` | 分页 | 200 Page&lt;KafkaMessage&gt; |
| GET `/kafka/messages/{id}` | UUIDv4 | 200 KafkaMessage |

### MySQLRecord

```json
{"id":"<UUIDv4>","name":"第一条记录","value":"你好 MySQL","created_at":"<UTC ISO8601>","updated_at":"<UTC ISO8601>"}
```

`name` trim 后 1..80 Unicode 字符；`value` 0..1000 字符，允许空字符串、不 trim。相同 name 允许。SQL 表 `lab_records` 与原任务表分开，参数化查询，无用户 SQL/表名/排序表达式。写入提交后重新查询，PUT 保留 id/created_at。

### RedisObservation

```json
{"key":"lesson-note","exists":true,"value":"你好 Redis","ttl_ms":9850,"observed_at":"<UTC ISO8601>"}
```

key 为 ASCII `[A-Za-z0-9_-]{1,64}`，仅服务端添加 `lab:kv:` 前缀；value 为 0..4096 UTF-8 字节；`ttl_seconds` 为必填整数 1..3600。PUT 覆盖并重置 TTL，回读实际值和 PTTL。GET/PTTL 来自同次原子快照，不接受用户 Redis 命令或 Lua。

- 不存在/已过期：`exists:false,value:null,ttl_ms:-2`，仍为 200；不能由缺失判断是过期、删除还是从未写入。
- 存在但没有过期时间：`ttl_ms:-1`，如实显示异常，不伪造到期；接口写入总会设置 TTL。
- TTL 单位为毫秒。UI 倒计时仅估算；必须新的 GET 才能确认观察时的存在性。
- 未配置/连接失败/操作失败为 503 `redis_unavailable`，不是空值。**原任务结果缓存可以降级，Redis 实验不能**。无 key 列表、SCAN 或全库清理。

### MongoDocument

```json
{"id":"<UUIDv4>","document":{"lesson":"MongoDB","tags":["JSON","read-back"]},"created_at":"<UTC ISO8601>","updated_at":"<UTC ISO8601>"}
```

只使用 `agent_lab.lab_documents`，不动 `agent_lab.results`。服务端 ID/时间戳在 wrapper 上，与用户 `document` 分开。POST/PUT 写后真实回读；PUT 替换整个 `document`，不是 `$set`/PATCH，保留 id/created_at。

JSON 根必须是 object；使用 `ensure_ascii=False,separators=(',',':'),allow_nan=False` 紧凑编码后最多 **16384 UTF-8 字节**。根容器深度为 1，嵌套 object/array 各加 1，最大 6；标量不增加容器深度。根、每个容器及标量值各计一节点，key 字符串不计，最多 200。拒绝非有限数、超出 BSON signed64 的整数、非法 Unicode；递归拒绝 `$` 开头或含 `.`/NUL 的 key。没有任意 collection、查询操作符、BSON 表达式或服务端代码。

浏览器数值仍有 JavaScript 精度限制，精确大编号请用字符串。HTML/脚本文本只作数据展示。

### KafkaMessage：确认发送不等于收到

固定 topic `agent.lab.messages.v1`、group `agent-lab-observer-v1`，单分区/单副本教学配置；调用者不能指定。key 同 Redis 字符规则；value 非空、最多 4096 UTF-8 字节。实际 Kafka key 是请求 key，value envelope 为 `{schema_version:1,id,key,value}`。

```json
{
  "id":"<UUIDv4>","topic":"agent.lab.messages.v1","key":"lesson","value":"你好 Kafka",
  "created_at":"<UTC ISO8601>","observed_at":"<UTC ISO8601>",
  "producer":{"status":"acknowledged","acknowledged_at":"<UTC ISO8601>","partition":0,"offset":12},
  "consumer":{"status":"received","received_at":"<UTC ISO8601>","group":"agent-lab-observer-v1","partition":0,"offset":12,"key":"lesson","value":"你好 Kafka"}
}
```

1. 先在 `lab_kafka_messages` 登记 id/key/value；初始 producer=`unconfirmed`、consumer=`not_observed`，对应观察字段均 `null`（group 固定非空）。不是任务 Outbox，不保证后台补发。
2. SQL 登记后进行一次有界发送；实际 delivery callback 成功才保存 `acknowledged`、真实 partition/offset 并返回 202。HTTP 202、flush 或入本地队列都不是消费者回执。
3. 未确认返回 503 `kafka_publish_unconfirmed`；已登记行保留，**不能推断绝未投递**。确认后 SQL 出错也可能返回 `database_unavailable`，此时消息可能已投递。
4. 同 ID 同 key/value 重复 POST 仅返回 200 当前快照，**绝不再发送**；同 ID 不同内容 409。未确认行不会靠重复 POST 自动修好；不要自动更换新 ID 重发。该防重复规则不是端到端 exactly-once。
5. 独立 Worker consumer 实际 poll，核对 envelope、Kafka key 与登记内容；持久化实际 key/value/partition/offset/时间后才同步提交该 offset。首次有效回执保持稳定；ack 和 receipt 分别更新，互不覆盖。
6. `unconfirmed + received` 可以同时成立。`not_observed` 仅表示尚无已提交的收取证据，不证明 Worker 离线、消息丢失或永远失败。短时观察结束后可手动 GET。
7. SQL/offset 提交失败重建 lab consumer、退避重读，不跨过失败消息；无效/未知 ID/不匹配协议拒绝回执。旧任务 consumer/relay/executor 语义保持独立。

登记与回执在 MySQL 保留并分页查询；没有 Kafka DELETE、重放或管理入口。历史回执证明曾收取，不证明 broker 现在仍保留原消息。

### lab 错误码

| HTTP | code | 处理 |
|---|---|---|
| 401 | `unauthorized` | 重新登录；不绕过认证 |
| 403 | `csrf_failed` / `origin_forbidden` | 核对新 CSRF 与实际同源入口 |
| 404 | `not_found` | 合法 ID 不存在；lab 不是按租户隐藏 |
| 409 | `message_id_conflict` | 同 ID 不同消息；没有再次发送 |
| 413 | `body_too_large` | 全局实际请求流超过 64 KiB |
| 422 | `validation_error` | 字段、类型、ID、分页或预算不合法，不调用下游 |
| 422 | `confirmation_required` | 没有显式确认，不执行删除 |
| 503 | `database_unavailable` | SQL/认证依赖故障；不能假成功 |
| 503 | `redis_unavailable` | 不是键不存在，不做实验降级 |
| 503 | `document_unavailable` | Mongo 操作或写后回读无法确认 |
| 503 | `kafka_publish_unconfirmed` | 按已知 ID 查询，不能认为绝未投递或自动重发 |
| 500 | `internal_error` | 脱敏兜底，保留 request_id |

网络错误或响应丢失不等于写入未发生。MySQL/Mongo 先刷新/回读；Kafka 保留发送前 ID 查询。UI 退出/切页取消等待也不能撤销服务端已经接收的写入。

## 原认证与任务接口（保留）

- POST `/api/v1/auth/register` 或 `/api/v1/auth/login`: `{username,password}`；返回 `{user:{id,username},csrf_token}` 并设置 HttpOnly `lab_session` cookie。
- GET `/api/v1/auth/me`: `{user:{id,username},csrf_token}`；会话失效 401。
- POST `/api/v1/auth/logout`: 需 `X-CSRF-Token`；204。
- 所有已登录写操作需 `X-CSRF-Token`；若有 Origin 则必须匹配 APP_ORIGIN。首次注册/登录也校验 Origin。CSRF token 内存保存；刷新通过 me 获取轮换的 CSRF token。
- POST `/api/v1/tasks`: `{prompt}`，需 `Idempotency-Key`（1..128），202 Task。
- GET `/api/v1/tasks?limit=20&offset=0`: `{items,total,limit,offset}`。
- GET `/api/v1/tasks/{id}`: Task。
- GET `/api/v1/tasks/{id}/events`: `{items:Step[]}`。
- GET `/api/v1/tasks/{id}/results`: `{task_id,content,model_mode,cache_status,execution_kind,controller_mode}`；尚未成功 409。
- Task: `{id,prompt,status,attempt_count,created_at,updated_at,error,result_available,model_mode,trace_id,progress}`。progress 为阶段值（0/10/30/100），不是模型完成百分比。
- Step: `{id,task_id,sequence,kind,content,created_at}`，仅公开安全动作摘要，无隐藏思维链。
- error: `{error:{code,message},request_id}`；所有响应有 X-Request-ID。
- `/healthz`、`/readyz`、`/metrics`。

认证是本地教学帐号 scaffold：无邮箱验证/找回/MFA/公网反滥用保证，不应公网部署。无默认帐号，测试创建临时帐号。所有任务读写绑定 owner。

原任务生产依赖：MySQL、Kafka、MongoDB；Redis 在原任务中是可失效进度/不可变结果缓存，lab Redis 实验则明确失败。LAB_MODE=test/demo 才允许 SQLite+内存文档/总线，必须在界面/就绪响应标注其非真实集成性质。

## 运行与边界

- API: `uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000`。
- 迁移: `uv run python -m backend.migrate`；API 启动不自动建表。
- Worker: `uv run python -m backend.worker`；健康检查 `python -m backend.worker --healthcheck`。
- 首版 worker **单副本**，relay 不支持竞争领取；consumer 与 executor 分线程，长模型调用不阻塞 Kafka poll。
- 就绪正文：`{status,mode,model_mode,dependencies}`；真实模式检查正确的 SQL schema v2（版本集合 `{1,2}` 和必要表/索引结构）、mongo、kafka；旧 v1/部分迁移不能 ready；test/demo 的 mongo/kafka 值为 `in_memory_test_adapter`。Redis 不作为关键就绪条件。
- test/demo 仅供进程内测试，不支持独立 worker 共用内存总线/文档；不可宣称真实组件集成。
- `/events` 返回 MySQL 持久化生命周期记录，实际组件、时间、trace_id；不是实时模型思维追踪。
- 每次 attempt 结果不可变；崩溃后的孤儿结果不自动跨 attempt 复用，因此可能重新调用模型并计费。尚无孤儿清理、跨 attempt 复用和完整分布式追踪。
- 认证无公网防暴力破解保证；仅本地教学。注册用户名 3..80 ASCII 字母数字下划线横线；密码 10..128 字符。


## 核心加固契约

`GET /api/v1/tasks/{id}/events`：MySQL 生命周期事件，含 Step 基础字段、`component` 和 `trace_id`。kind 为 pending/outbox_sent/ready/running/retry_wait/failed/succeeded；component 为 api/relay/consumer/executor/recovery。仅真实事务落库时创建，最多100条。

`GET /api/v1/tasks/{id}/attempts`：`{items:[{id,fence,started_at,finished_at,outcome}]}`，最多100条，始终先校验所有权。

结果响应 `cache_status` 为 `hit` / `miss` / `unavailable` / `disabled`。先 SQL 授权和确定不可变 result_id，再 Redis cache-aside；缓存失效时读 Mongo，TTL300秒。Redis 不是状态权威，停机可降级。结果引用按 attempt 分版本，无需修改已缓存结果。

用户名统一规范化为小写；密码 scrypt N=16384/r=8/p=5。MAX_ATTEMPTS 1..100，LEASE_SECONDS >0。实际请求流最大64KiB（不仅校验Content-Length）。

## 故障验收开关（默认关闭）

仅在隔离测试进程设置 `LAB_TEST_HOOKS=true` 与 `LAB_TEST_PAUSE_AT`。允许点：`after_outbox_publish`、`after_inbox_commit`、`after_claim`、`after_mongo_save`。命中后创建 `/tmp/lab-hook-<point>`（内容PID）并暂停60秒，便于测试 kill/restart；没有 HTTP 控制入口。每轮删除旧 marker，重启恢复时移除开关。它不是正常运行配置。

MongoDB 选择/连接超时2秒、socket3秒、操作预算5秒；PyMySQL connect3/read5/write5秒。单 Agent 使用异步可取消 HTTP；每I/O30秒之外还执行单调时钟总deadline，最大60秒且受实际SQL租约剩余时间减15秒持久化余量限制。首轮未实现跨attempt结果复用；遗留文档只可能成为孤儿，不允许旧fence更新SQL成功。外部调用可能重复。

Kafka 启动显式建立开发用单分区、单副本的任务、DLQ 与独立教学主题；这不是生产高可用配置。relay/consumer/executor分线程，consumer持久化inbox后再提交该消息offset。原始幂等键按字节UTF-8摘要保存，大小写及尾空格不同即不同键。


## 受限单 Agent：具体响应契约

原单 Agent 历史实现状态：运行时、真实组件与浏览器教学链路已验收，见[单Agent验收报告](AGENT_TEST_REPORT.md)；真实 provider 仅有独立接口连通性检查，尚未完成工具调用及全栈 live 验收；不能以脚本或 mock 替代。
`POST /tasks` 仍仅接受 `{prompt}`（1..10000字符，trim后幂等摘要）。材料就是完整prompt，材料标识为 `task_input`，没有独立附件。

### 可复现脚本示例（没有真实模型推理）

```json
{"prompt":"目标：[search:销量] [stats]\n材料：销量 10 20 30"}
```

`scripted_test` 策略先读取最多1000字符；`[search:字面词]` 触发字面搜索（从 `材料：` 后开始，无材料标记则从search标记之后开始）；`[stats]` 且有非空 `材料：` 才统计材料范围。若搜索无命中，直接final，不继续stats。没有明确markers的普通输入只read→final，不自动提取UUID/测试ID数字。最终答复为明确标注的脚本摘要而非自主理解。`live_llm` 由模型根据观察选择工具或立即final，不强制此序列；本轮不启用真实模型。

`GET /api/v1/tasks/{id}/results` 新结果示例：
```json
{"task_id":"TASK","content":"[deterministic 脚本测试控制器；无真实模型推理]\n…","model_mode":"deterministic","cache_status":"miss","execution_kind":"single_agent","controller_mode":"scripted_test"}
```

`GET /api/v1/tasks/{id}/agent-steps` 返回对象：
```json
{"items":[{"id":"ATTEMPT:1","task_id":"TASK","attempt_id":"ATTEMPT","sequence":1,"kind":"tool_call","content":"调用只读工具 read_text","created_at":"2026-10-22T00:00:00+00:00","execution_kind":"single_agent","controller_mode":"scripted_test","tool_name":"read_text","arguments":{"offset":0,"length":1000}}],"availability":"committed","execution_kind":"single_agent","controller_mode":"scripted_test"}
```
此简例只展示第一条；完整demo有7条：tool_call/tool_result各三对，最后final。sequence从1连续，稳定id是attempt_id:sequence。每条均有上述基础字段；tool_call含tool_name/arguments，tool_result再含result对象与truncated布尔值，final.content为最终答复且无工具字段。无隐藏reasoning/thought/provider历史。

工具result形状：
- read_text: `{source:"task_input",offset,text,next_offset,truncated}`；offset/next_offset按Unicode字符，实际JSON UTF-8≤4096字节，next_offset仅跳过实际返回字符。
- search_text: `{source:"task_input",matches:[{position,end,snippet_offset,snippet}],next_offset,truncated}`；位置按字符，完整命中对象，最多5条。next_offset指向下一待返回命中，或确已完成时指向输入末尾；可用offset继续，不漏命中。
- numeric_stats: `{count:3,sum:"60",min:"10",max:"30",mean:"20"}`；Decimal结果为确定性字符串（64位精度），count为整数，无数字时其余为null。脚本策略只统计材料标记后的文本；工具本身和live控制器可用start/end选择本任务prompt内任一合法字符范围。仅支持ASCII十进制、最多200个、token≤32字符、绝对值≤10^12；`1e6`、`1,000`、`1，2`、`$10`、`item2`、NaN/Infinity等拒绝，不拆子数字；`1、2、3`有效。这是词法统计，不是日期/财务语义解析。

成功之前（包括running/failed）返回：
```json
{"items":[],"availability":"not_committed","execution_kind":null,"controller_mode":null}
```
这不证明没有调用过工具，只表明没有可读的成功提交轨迹。失败与崩溃attempt的工具轨迹不持久化，本接口不是实时审计。`/events`仍是SQL后台生命周期，`/attempts`仍是SQL执行尝试。

仅当旧文档的execution_kind与controller_mode两字段均缺失时，items为空、availability=legacy，execution_kind=legacy_single_call；controller_mode按旧model_mode取legacy_deterministic_echo或legacy_live_single_call。results也补充此标记；不改写旧Mongo文档、不将旧summary伪装成Agent动作。若元数据存在但无效或缺一字段，返回503/document_unavailable，不误标为legacy。

两接口始终先SQL所有权+成功result_id验证，再共用Redis不可变结果缓存/Mongo读取。未登录401、非所有者404；有成功引用但文档不可读503/document_unavailable，不能返回伪空；results在未成功时仍409/result_not_ready。

### 预算、安全错误与费用

每attempt最多6决策/5工具/1final；参数2KiB、工具结果4KiB、工具结果累计16KiB、final8KiB、provider每次请求与响应各64KiB、每次输出1024tokens。实际时间=min(60秒, lease_until-now-15秒)，不足不调用；无final或预算耗尽不成功。仅三个只读工具，无shell/文件/网络工具或副作用。provider请求把prompt及观察发送到显式配置的HTTPS地址，需要live模式、ALLOW_LIVE_MODEL及私密key/model配置；不会静默降级。

任务error.code安全允许列表新增：agent_protocol_error、agent_tool_rejected、agent_budget_exceeded、agent_refused、agent_configuration_error（永久）；provider_transient_error（429/5xx/预算尚存的传输故障，沿现有有限attempt重试）。不保存provider原始错误/凭据。工具格式unsupported_numeric_format作为安全内部拒绝原因，任务公开code仍agent_tool_rejected。旧通用permanent_failure/transient_failure/lease_expired保留；不持久化任意异常code。

协议拒绝多tool_calls、截断、空final、重复call_id或未知结束原因；合法单tool_calls伴随assistant辅助文本会忽略辅助文本而不是拒绝。异步总deadline可取消等待、响应超限停止读取，不代表provider端取消计费。每attempt最多6个provider请求，总计最多6×MAX_ATTEMPTS；默认3次attempt时18，不承诺只调用/计费一次。该历史单 Agent 协议本身不新增 SQL schema/租约心跳，不改变 Outbox/Inbox/fencing 提交规则；本轮 lab schema v2 是独立增量。
