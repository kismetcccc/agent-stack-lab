# 组件操作台：有限迭代计划与实施契约

更新：2026-10-22。状态：**计划已定，尚未实现或验收**。本文件是新一轮 `PLAY-01..07` 的计划，不重开、不改写已完成的[学习型 v1 计划](DEVELOPMENT_PLAN.md)。协调者先发布本计划，再实施；每项状态只能由对应提交的实际证据更新。

## 1. 这一轮交付什么

用户要的是「前端直接操作后端组件」，不是必须先提交 Agent 任务才能看的链路或拓扑图。入口成为四个独立操作台：

| 操作台 | 用户直接做的事 | 成功的真实证据 |
|---|---|---|
| MySQL | 新建、列表、读取、修改、确认删除教学记录 | SQL 提交后重新查询的记录；刷新/重启仍在 |
| Redis | 按 key 写值和 TTL、读取、再次读取、确认删除 | Redis 实际 GET/PTTL；到期后真实不存在 |
| MongoDB | 新建、列表、读取、替换 JSON 文档、确认删除 | 真正写入独立 collection，并重新读取的 JSON |
| Kafka | 发送小消息、查看记录、刷新实际消费者回执 | 分开显示 producer 确认和 Worker 真正消费后持久化的回执 |

**无需创建 Agent 任务，无模型调用、无模型 key、无收费服务。** 保留原任务页与教学架构说明，但不将它们当操作台前置条件。默认进入操作台；桌面/手机均可操作。原任务、账号、结果和授权语义不改变。

这是个人本地教学工具。用户明确不需要多租户/账号隔离：新增教学数据为所有已登录本地账号共享，**不加 `owner_id`、tenant、账号配额、租户过滤或新身份层**。共享教学数据不等于删除认证：继续使用原登录、会话 cookie、CSRF 和 Origin 检查；原 `/tasks` 的资源所有权检查完整保留。页面明确提示「本机共享教学数据，不存放秘密」。

### 不做

不增加 raw SQL、任意 Redis 命令/Lua、Mongo 查询语法、Kafka topic/group/offset 管理控制台；不加批量清库、Kafka 重放、broker 消息删除、全局重置、账号配额、通用平台层、Kubernetes、第三方服务、多 Agent、模型评测或 live 模型调用。保留 loopback 绑定，不改账号/数据库/模型秘密，不新增 `LICENSE`，不运行 `npm audit`。

## 2. 已检查的基线与接入点

基线为 `b76947dba96978b0cd30991350bb834ab49f48d4`（来源代码父提交 `102491d2`）。协调者已确认该基线 409 项离线测试及真实 CI 为绿；这是继承证据，不是本计划已重跑了测试。历史报告保留原被测提交。

| 已检查的源码 | 本轮决定 |
|---|---|
| `backend/app.py`：统一错误、64KiB 实际流上限、Auth、`/readyz` | 追加 `/api/v1/lab`，复用认证/错误边界；不得改成匿名管理接口 |
| `backend/migrate.py`：目前只有 `create_all` 加 v1 标记 | 改成真正、可重复且可恢复的显式 v1→v2 迁移；不能把扩大后的 metadata `create_all` 称作升级 |
| `backend/db.py`：账号、任务、结果引用、outbox/inbox 等现存表 | 新建两张独立 lab 表；不改旧数据及所有权 |
| `backend/adapters.py`：Mongo `agent_lab.results`；Redis 可降级结果缓存；Kafka publish 绑定 task_id | lab 使用独立适配器方法/命名空间；不要复用会吞错的缓存写入，也不伪造 task_id 发送 lab 消息 |
| `backend/worker.py`：现有 relay/executor 线程及任务 consumer | 仅增加固定教学 topic 的独立 consumer loop；不新增服务或凭据，不干扰任务 consumer/group |
| `frontend/src/App.tsx`、`Explorer.tsx`、`api.ts` | 复用登录/CSRF/请求取消；新增直接操作页，旧拓扑作为可选说明 |
| `compose.yaml`、`compose.ui.yaml`、CI、真实 integration/e2e | 继续后端 8080、可选同源 UI 8081；新增迁移/组件/浏览器真实验收，旧回归不删 |

云端当前 checkout 没有 `.git`、没有 Docker daemon。这里可以编写、运行可用的离线检查，但不能宣称已完成真实 Compose 或浏览器全栈验收；由有 Docker 的真实 CI 执行，协调者核验准确提交后再更新用户本机。

## 3. 最小 API 通用契约（冻结）

- 前缀 `/api/v1/lab`；这是 **HTTP API v1** 的新增路由，不改旧 API。数据库迁移目标为 **schema v2**；Kafka 消息 envelope 为 **schema_version 1**。行对象没有乐观锁 `version`；PUT 是完整替换可编辑字段，后提交覆盖先提交。
- 全部路由要求有效登录；写操作（POST/PUT/DELETE）要求现有 `X-CSRF-Token` 和 Origin 规则。不要求创建 task，不接受 owner/tenant/topic/group/数据库连接参数。
- 请求 JSON 拒绝未知字段与非法类型；字符串不把数字强制转成文本；TTL 不接受 bool/float。拒绝非法 Unicode surrogate。全局实际 HTTP 请求体仍为 64KiB 上限，组件还有下述更小界限。
- 服务端创建 MySQL/Mongo UUIDv4；Kafka UUIDv4 由调用端在发送前创建。ID 路径必须是 UUIDv4；非法 ID 为 422，合法但不存在为 404。
- 所有时间为 UTC ISO 8601 字符串；nullable 字段明确返回 `null`，不省略。`observed_at` 表示本次服务端观察时间，不是组件全局时钟或持续在线证明。
- MySQL/Mongo/Kafka 列表参数：`limit` 默认 20，范围 1..50；`offset` 默认 0，范围 0..10000。响应 `{items,total,limit,offset}`，按 `created_at DESC, id DESC` 排序。分页是有界读取，不是租户配额；并发写入时不承诺跨分页快照一致性。
- 每次删除必须显式 `?confirm=true`；缺失或 false 返回 422/`confirmation_required`。UI 先显示具体对象及确认/取消按钮，取消不发 DELETE。不提供删除全部。
- 所有响应保留 `X-Request-ID`。错误保持 `{error:{code,message},request_id}`，不含异常栈、原始组件错误、连接串或秘密。错误不包装成空列表/空文档/假成功。
- test/demo 仅允许显式替身用于离线测试；界面按 `/readyz.mode` 明示「测试/演示替身」。`production` 只表示真实适配器，不表示生产安全。模式未知时不宣称真实连接。生产 lab 操作不得静默回落到内存替身。

### 路由表

下表路径均在 `/api/v1/lab` 下。

| 方法与路径 | 输入 | 成功状态/响应 |
|---|---|---|
| POST `/mysql/records` | `{name,value}` | 201，MySQLRecord |
| GET `/mysql/records` | 有界分页 | 200，Page&lt;MySQLRecord&gt; |
| GET `/mysql/records/{id}` | UUIDv4 | 200，MySQLRecord |
| PUT `/mysql/records/{id}` | `{name,value}` | 200，重新查询的 MySQLRecord |
| DELETE `/mysql/records/{id}?confirm=true` | 无 body | 204；已不存在为 404 |
| PUT `/redis/keys/{key}` | `{value,ttl_seconds}` | 200，RedisObservation |
| GET `/redis/keys/{key}` | 合法 key | 200，RedisObservation；不存在也是 200 |
| DELETE `/redis/keys/{key}?confirm=true` | 无 body | 204，包括已过期/不存在 |
| POST `/mongo/documents` | `{document:object}` | 201，MongoDocument |
| GET `/mongo/documents` | 有界分页 | 200，Page&lt;MongoDocument&gt; |
| GET `/mongo/documents/{id}` | UUIDv4 | 200，MongoDocument |
| PUT `/mongo/documents/{id}` | `{document:object}` | 200，重新读取的 MongoDocument |
| DELETE `/mongo/documents/{id}?confirm=true` | 无 body | 204；已不存在为 404 |
| POST `/kafka/messages` | `{id,key,value}` | 首次 broker 确认后 202；相同请求重查为 200；KafkaMessage |
| GET `/kafka/messages` | 有界分页 | 200，Page&lt;KafkaMessage&gt; |
| GET `/kafka/messages/{id}` | UUIDv4 | 200，KafkaMessage |

### 错误状态/代码

| 状态 | `error.code` | 语义 |
|---|---|---|
| 401 | `unauthorized` | 未登录/会话失效，原认证契约不变 |
| 403 | `csrf_failed` / `origin_forbidden` | 原 CSRF/来源保护不变 |
| 404 | `not_found` | 合法 ID 的教学记录不存在；不是租户隐藏语义 |
| 409 | `message_id_conflict` | Kafka 相同 ID 但 key/value 不同；不发送 |
| 413 | `body_too_large` | 超过原全局 64KiB 实际流上限 |
| 422 | `validation_error` | DTO/UUID/分页/组件大小/TTL/JSON 不合法；不调用下游 |
| 422 | `confirmation_required` | 删除未显式确认；不删除 |
| 503 | `database_unavailable` | SQL 或认证依赖不可用；不伪造记录 |
| 503 | `redis_unavailable` | 未配置 Redis、连接失败或操作失败；实验不做缓存降级 |
| 503 | `document_unavailable` | Mongo 不可用或写后读取无法确认；不回显请求冒充落库 |
| 503 | `kafka_publish_unconfirmed` | 未获得/未能确认发送结果；已登记 ID 可查，不能据此认定绝未投递 |
| 500 | `internal_error` | 脱敏兜底，保留 request_id |

SQL 在 broker 确认之后失效时可能仍返回 `database_unavailable`，消息可能已投递；调用端按已知 ID 重查，而不是自动重发。任何网络/写入响应丢失也不等于操作绝未发生。

## 4. 四个独立组件的字段与观察语义

### 4.1 MySQL：固定记录 CRUD

```json
{"id":"<UUIDv4>","name":"第一条记录","value":"你好 MySQL","created_at":"<UTC ISO8601>","updated_at":"<UTC ISO8601>"}
```

`name` trim 后 1..80 Unicode 字符，`value` 0..1000 Unicode 字符（允许空字符串，不 trim）；相同 name 允许。存储仅用新表 `lab_records`，主键 id，`created_at,id` 排序索引。SQL 参数化；没有任意表名、列名、where、order 或 SQL 输入框。写操作提交成功后读取真实记录；刷新页面不依赖浏览器内存。

### 4.2 Redis：真实 KV/TTL，不是可降级结果缓存

key 为 ASCII `[A-Za-z0-9_-]{1,64}`，真实 key 由服务端固定加 `lab:kv:` 前缀。用户无法触及 `result:`、`progress:` 或任意 Redis 命令。value 是 0..4096 UTF-8 字节的字符串，TTL 为必填整数 1..3600 秒；PUT 替换同 key 并重置 TTL。

```json
{"key":"hello","exists":true,"value":"你好 Redis","ttl_ms":29864,"observed_at":"<UTC ISO8601>"}
```

- `ttl_ms` 来自真实 PTTL；GET+PTTL 必须是同一次原子快照。可用固定内部 Lua/事务，**不可接受用户脚本或命令**。PUT 同样回读刚写入的实际值/PTTL。
- 已过期/不存在：`exists:false,value:null,ttl_ms:-2`。存在但没有 TTL：`ttl_ms:-1`，如实提示异常无过期，不换算成「已到期」或编造数字；接口自己创建的 key 都有 TTL。
- UI 的「再次读取」重新调用 API。若显示本地倒计时，必须标为估算；到期事实只能由新 GET 的 `exists:false` 确认。最小版可只显示带观察时间的服务器 TTL 快照。
- 不提供 key 列表/SCAN/KEYS 或批量清理；本轮是按指定 key 的直接实验。Redis 停机/未配置明确 503，现有任务结果缓存仍可降级，两种语义必须分开测试。

### 4.3 MongoDB：真实 JSON 文档 CRUD

```json
{"id":"<UUIDv4>","document":{"lesson":"MongoDB","tags":["JSON","read-back"]},"created_at":"<UTC ISO8601>","updated_at":"<UTC ISO8601>"}
```

使用独立 collection `agent_lab.lab_documents`；服务器 `_id`/时间戳与用户 `document` 包装分开。原 `agent_lab.results` 及结果缓存完全不动。写后再读真实 Mongo 文档，不返回输入副本冒充读取；PUT 只替换 `document`，保留 id/created_at。

JSON 根必须是 object；紧凑 `ensure_ascii=False,separators=(',',':'),allow_nan=False` 编码 UTF-8 后最多 16384 字节。根 object 的容器深度为 1，嵌套 object/array 各加 1，最大 6；标量不增加容器深度。根与每个容器/标量值各计一个节点（不计 key 字符串），最多 200。拒绝非有限数与超出 BSON signed64 的整数。递归拒绝 `$` 开头、含 `.` 或 NUL 的 key；拒绝非法 Unicode。无 BSON 表达式、查询操作符、用户指定 collection 或服务端代码。

浏览器 JSON 数值遵循 JavaScript 的精度限制；需要精确保存超大编号应使用字符串，不宣称浏览器 number 任意精度。HTML/脚本文本只作为普通 JSON/文本展示，不能通过 innerHTML 执行。

### 4.4 Kafka：确认发送与实际收取是两个事实

固定 topic `agent.lab.messages.v1`（单分区/单副本开发配置）与消费组 `agent-lab-observer-v1`，由现有 Worker 初始化固定 topic，不允许调用者改名字。不新增 broker 凭据、外部服务或独立 Worker 部署。保留旧任务/DLQ topic 和任务消费组，互不混用。

POST 请求：`id` 为调用端预先生成的 UUIDv4；`key` 为 `[A-Za-z0-9_-]{1,64}`；`value` 为非空字符串，最多 4096 UTF-8 字节。真实 Kafka key 为请求 key，值 envelope 固定为：

```json
{"schema_version":1,"id":"<UUIDv4>","key":"lesson","value":"你好 Kafka"}
```

KafkaMessage：

```json
{
  "id":"<UUIDv4>","topic":"agent.lab.messages.v1","key":"lesson","value":"你好 Kafka",
  "created_at":"<UTC ISO8601>","observed_at":"<UTC ISO8601>",
  "producer":{"status":"acknowledged","acknowledged_at":"<UTC ISO8601>","partition":0,"offset":12},
  "consumer":{"status":"received","received_at":"<UTC ISO8601>","group":"agent-lab-observer-v1","partition":0,"offset":12,"key":"lesson","value":"你好 Kafka"}
}
```

1. API 先在独立表 `lab_kafka_messages` 提交 id/key/value/created_at，初始 producer 为 `unconfirmed`、consumer 为 `not_observed`，其余相应观察字段均 `null`（group 固定非空）。这不是 task/outbox，也不保证后台自动重发。
2. 然后事务外做**一次有界 producer 发送**。只有真实 delivery callback 成功才记 `acknowledged` 和 callback 的 partition/offset，并返回 202。不得把本地排队/flush 开始/HTTP 202 当消费成功。
3. 超时/error 没有确认就返回 503/`kafka_publish_unconfirmed`；已登记行保留 `unconfirmed`。不能说「一定没发送」，也不能自动补发。客户端已知道 id，可重查。发送前 SQL 失败则不调用 producer。
4. 相同 id+相同 key/value 再次 POST 返回 200 当前快照，**绝不再次 publish**；不同 payload 为 409。此规则防止重复点击/响应丢失导致盲重发，不宣称全链路 exactly-once。首次请求中断的 unconfirmed 行不会被重复 POST 自动修复。
5. Worker 增加独立 consumer loop/group，真实 poll 收到 envelope 后，校验 envelope、实际 Kafka key 和已登记 id/key/value；把实际读到的 key/value、partition/offset、received_at 写入该行。首次有效回执稳定，重复消费不覆盖；**SQL 提交后才能同步提交该 message offset**。
6. receipt 与 producer ack 更新分离，只更新各自列，防止消费先到时被 API 覆盖。可能出现 `producer:unconfirmed` 与 `consumer:received`：例如 broker 已送达但 API 的确认写入中断。不能从一方反推另一方。
7. SQL/offset 提交失败：关闭并重建 lab consumer，短退避后重读未提交位置，不继续跨过失败消息。任务 consumer/relay/executor 不被 lab 异常吞并。固定协议之外、过大、无法解析、不认识的 id 或不匹配 payload：拒绝回执，可提交该无效 record 并只记录脱敏原因；不可把数据库故障误分成无效 record 而跳过。固定 topic 不是任意事件收件箱。
8. `not_observed` 只表示数据库尚无已提交的实际收取证据；不代表 worker 在线/离线、消息丢失或永远失败。UI 显示「生产确认 / 消费者收取」两栏；可短时轮询（上限 20 秒），到时写「尚未观察到，可手动刷新」，不是失败或假进度。

**列表/保留/清理：**共享消息登记与回执在 MySQL 持久保留、分页展示，刷新/重启可查；本轮没有 Kafka DELETE、重放或清理入口。Kafka broker 自身保留策略沿用现有配置，不承诺永久保留消息。历史回执证明曾收取，不证明 broker 现在还保留该 payload。MySQL/Mongo 教学记录只按确认的单条删除，Redis 按 TTL/单 key 删除；不删除任务、结果、账号或数据卷，不把 `down --volumes` 放入普通更新流程。

## 5. v1→v2 真实迁移与兼容性门槛

迁移只增加 `lab_records` 与 `lab_kafka_messages` 及它们的固定索引；不含 owner/tenant 字段。后者保存提交内容、producer 确认元数据、首个实际消费回执，id 主键用于幂等；两表都必须被真实 MySQL 集成测试检查。

1. 保持 `python -m backend.migrate` 作为唯一显式入口；API 启动不得自动建表。拆开/冻结 v1 的原表集合；全新数据库按 v1 初始化→v2 的顺序执行。
2. 已有且结构符合 v1 的库：识别版本记录 `{1}`，只执行显式 v2 增量步骤。保留所有旧 users/sessions/tasks/outbox/inbox/attempts/task_events 和原索引/约束/内容；保留 v1 标记，v2 完成后追加 2，不把历史标记改名。
3. v2 每张表/索引的存在和结构必须检查。MySQL DDL 会有隐式提交，不能声称把整个升级包裹在一个可回滚事务中。中途退出时可识别已经正确创建的 v2 对象，验证结构后补齐剩余步骤，最后才写版本 2；未知/冲突结构必须非零退出，不能覆盖或假装成功。
4. 版本集合只有空白新库、`{1}`、`{1,2}` 可按相应路径处理。未知未来版本、缺 v1 的 v2、无版本但存在不完整业务表等状态，在任何自动变更前拒绝；给脱敏诊断。不为通过测试删库或自动「修复」未知 schema。
5. 第二次/重启后 migrate 为无数据改变的成功；schema v2 标记不能掩盖缺失/错误的新表。只保证本轮显式两版本升级，不新增通用迁移平台或自动降级。
6. `/readyz` 保留 `{status,mode,model_mode,dependencies}` 外形，SQL 项改为要求正确 v2 版本和必要 lab schema；旧 v1、部分迁移、错误/未来 schema 返回 503/not_ready，不能因为 `version=1` 仍存在而 ready。Redis 继续不决定原系统全局 ready；实验自身 Redis 操作仍 fail-closed。
7. Worker 使用 v2 前也须明确检查/依赖迁移成功。Compose 继续 migrate completed_successfully→API/Worker。旧 readiness/fixture/schema 断言必须同步，而不是删除相应测试。
8. 不自动回滚/降级 schema。需要回退代码时保留数据卷，并先确认兼容；恢复备份是单独的显式运维动作，不借升级清空库。

## 6. UI 交互验收

- 登录后默认组件操作台，四张卡片/页签直接进入 MySQL、Redis、Mongo、Kafka；无任务 prerequisite、无链路式进度导航。已有账号登录继续可用。
- 每页包含：用途一句话、可编辑输入、操作按钮、真实响应/数据、错误与 request_id；用当前事实而非漂亮动画解释能力。
- MySQL/Mongo 可新增、选中、加载、完整替换、删除；删除确认显示对象，取消/关闭/切换页不发送请求。保存时禁重复点击；成功从服务端响应/重查更新列表，不凭本地数组宣布落库。
- Redis 可指定 key/value/TTL、写入、读取、再次读取及确认删除；显示真实 TTL 单位和观察时间，清楚区分缺失与依赖故障。
- Mongo 编辑器先提示 JSON 解析错误，服务端仍完整校验；输入保持文字，不执行 HTML。回读结果和编辑草稿不互相伪装。
- Kafka 发送前生成/保留 ID；返回不确定/请求被取消时仍可按该 ID 查询；不得自动用新 ID 重发。历史列表可刷新，两个观察状态分别展示。若用户主动发送一条新消息，明确这是另一次发送，可能与此前不确定消息重复。
- 请求取消、切换组件/对象、浏览器 Back/Forward、logout、CSRF 轮换、重复点击和过期响应都有保护；旧请求不能覆盖新页面/对象，不把失效身份藏成组件错误。
- 页面刷新后 MySQL/Mongo/Kafka 从真实 API 重载；Redis 指定 key 重读。没有全局 online 绿灯冒充所有操作成功，也不把 `/readyz` ready 当消费完成。
- 桌面 1440×1000、手机 390×844 下输入/JSON/表格/确认区域可用，无页面级横向溢出；字段有 label，键盘能确认/取消。旧任务/架构/单 Agent 测试继续保留。

## 7. 有限里程碑：计划→实现→测试→文档→本机更新

状态只用：待开始 / 进行中 / 已实现待验收 / 已验收 / 阻塞。文档完成不等于运行验收。

| ID | 工作 | 初始状态 | 验收产物与门槛 |
|---|---|---|---|
| PLAY-01 | 冻结本计划、Agent.md 当前优先级、协调后端/前端/测试契约 | 进行中 | 计划先发布到远端可核验提交；各方使用同一路由、字段、错误及数据命名空间 |
| PLAY-02 | 后端四组件操作、独立存储、固定 Kafka consumer 和 v1→v2 | 待开始 | 真实适配器实现；有界输入；无 task/model prerequisite；旧授权/缓存/队列不变；离线针对性测试通过 |
| PLAY-03 | 直接操作台 UI | 待开始 | 四组件完整操作、确认/取消、错误/空态、刷新/导航/重复请求保护；类型检查、单元、构建通过 |
| PLAY-04 | 真正 Compose 与故障/升级验证 | 待开始 | 下方真实集成矩阵全部通过；旧真实链路/故障窗口不退化；只在隔离合成环境停止依赖 |
| PLAY-05 | 真实浏览器桌面/手机验证 | 待开始 | 下方浏览器矩阵通过，实际页面截图复核；mock 网络测试只作为补充 |
| PLAY-06 | 更新接口/教程/运维/报告及精确提交 CI | 待开始 | OpenAPI、API_CONTRACT、UI_GUIDE、README/文档索引及报告一致；最新远端提交完整必需 CI 绿；记录真实/替身/未运行，检查秘密/链接 |
| PLAY-07 | 协调者更新已有本机栈并验收 | 待开始 | 云端 CI 之后，使用独立忽略的 `.env.compose.local` 和已有卷，显式迁移、构建/重启、8081 浏览器 smoke；旧数据保留，真实四操作成功；不改模型 key |

### 必需测试矩阵

| 层级 | 必测内容 | 不能被什么替代 |
|---|---|---|
| 离线/单元/API | 所有合法/边界/非法输入、未知字段、UUID、UTF-8/JSON预算、CSRF/未登录/确认、共享数据两账号互可见、旧 tasks 跨账号仍拒绝；Redis 故障不吞错；Kafka 同 ID 无重发/冲突/ack 与 receipt 并发不互覆盖 | 不能据此声称真实 Redis/Mongo/Kafka 已测 |
| 真实 MySQL 迁移 | 独立真实库以冻结 v1 schema 播种合成账号、会话、任务/相关旧行；v1 ready 拒绝；执行 v2 两次、重启后再查，旧数据/约束/认证保留、新对象存在；部分 DDL 断点可恢复；未知/冲突版本/结构拒绝 | SQLite 或当前 metadata 创建的「假 v1」不是 v1→v2 证据 |
| 真实 CRUD/命名空间 | HTTP 新增/改/读/删并直接核对 MySQL、Mongo；API/服务重启保留；两账号共享 lab，但 tasks/results 原授权和数据不变；Mongo 换 collection，不触碰 results | UI 回显输入、内存 store 或只 ping 不够 |
| 真实 Redis | 写入短 TTL，真实值与 PTTL 对上；再次 GET TTL 下降；等待到期后真实缺失；覆盖重置 TTL；确认删除；停止 Redis 时 lab503，恢复后可操作且原任务结果仍可降级 | 本地倒计时/模拟时间不是过期证据 |
| 真实 Kafka | POST 回调元数据与 broker/receipt 相符；实际 Consumer 读到相同 key/value；暂停 Worker→send 已确认但未观察→恢复 Worker 真正收到；Worker 重启后回执稳定；Kafka 不可用发送报未确认，查 ID 不伪成功/自动重发 | producer.flush、HTTP202、静态状态或任务 consumer 不是 lab receipt |
| 真实依赖错误 | 停 Mongo 返回 document_unavailable、恢复能回读；MySQL 不可用不伪成功；旧 fault-window/HTTP smoke 保留；故障清理恢复检查 | 仅请求拦截错误是 UI 测试，不是组件 outage |
| 真实浏览器 | 使用实际 Compose 同源8081登录；四组件无需创建 task；MySQL/Mongo增改删+取消；Redis真实到期；Kafka发送并收到；刷新恢复；手机/桌面；旧任务仍工作 | Vitest、构建和 API-only测试不能替代 Chromium |
| 浏览器补充 | 重复点击、Close/Cancel、切页/对象、Back/Forward、请求乱序、logout/会话失效/CSRF轮换、错误文案、长JSON/HTML文本安全 | 可拦截网络精确制造竞态，但要标为补充，不冒充真实故障 |

运行沿用仓库既有入口：后端 `uv run pytest backend/tests tests/judge/test_capture.py -m 'not integration'`、ruff；前端 `npm ci --no-audit`、typecheck/test/build；真实 Compose 后 `bash scripts/test-integration.sh`、既有 crash-window/HTTP smoke；UI overlay 后 `TEST_BASE_URL=http://localhost:8081 bash scripts/test-e2e.sh`。新增测试/脚本由对应负责人接入 CI，离线与真实矩阵分开计数。真实依赖/浏览器不可用应准确写「未运行/阻塞」，不以旧基线绿灯充当本轮通过。

### 本机更新边界

本计划作者/云端代码子任务不操作用户电脑。协调者在云端完整 CI 后，检查用户电脑现有 checkout、独立 `.env.compose.local`、Compose project/卷及服务状态；不把云端 `.env` 拷过去，不重新生成已有密码，不修改模型 key。确认目标提交、沿用已有 project/volumes，显式运行 v2 迁移并保留输出，再更新 API/Worker/UI。普通更新不使用 `down --volumes` 或重建空库。回读旧账号/任务及新 lab 数据，最终在 `http://localhost:8081` 做真实 smoke；任何权限/环境阻塞具体说明，不能把「云端 CI 绿」说成「本机已更新」。

## 8. 收口条件与证据记录

`PLAY-01..07` 满足各自门槛后结束这一轮；不为延长迭代添加组件、模型、租户平台、Kafka admin 或重放实验。若本机阶段确实被环境/权限阻塞，明确报告云端已完成、本机未完成与所需动作，不冒充全部交付；无授权的动作保持等待，不绕过限制。许可证、live 全栈、Kubernetes 等沿用旧计划独立状态，不是这一轮前置条件。

每项报告记录：起止/远端 commit、改动文件、实际命令、执行环境、真实依赖或替身、通过/失败/未运行、测试数量、脱敏证据路径、发现的问题及修复、服务恢复/数据保留情况。本计划撰写时只有源码/契约检查，没有新增功能运行证据。

## 9. 核对依据

本轮技术依据以已锁定依赖与实际代码/测试为主；官方语义于 2026-10-22 核对：

- `create_all` 只条件创建 metadata 中的表，长期 schema 演进需要显式增量管理；因此本轮冻结 v1、追加可识别的 v2，而不是扩大 `create_all` 后改版本号。[SQLAlchemy MetaData](https://docs.sqlalchemy.org/en/20/core/metadata.html) / [Schema evolution](https://docs.sqlalchemy.org/en/20/tutorial/metadata.html)
- MySQL DDL 隐式提交，不能用外层事务承诺多 DDL 自动回滚；迁移需要可恢复步骤及最后版本标记。[MySQL 8.4 implicit commit](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html)
- PTTL 是毫秒，负值区分不存在与无到期时间。[Redis PTTL](https://redis.io/docs/latest/commands/pttl/)
- Kafka 手工同步 commit 与消息 offset 有明确语义；本轮在实际 receipt 持久化后提交，保留至少一次消费和确认不确定性的边界。[Confluent Python consumer](https://docs.confluent.io/kafka-clients/python/current/overview.html) / [Client API](https://docs.confluent.io/platform/current/clients/confluent-kafka-python/html/index.html)
