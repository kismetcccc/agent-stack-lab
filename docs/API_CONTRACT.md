# 冻结的首轮 API 契约

内部 API 端口 8000，默认宿主后端端口 8080，可选学习界面网关 8081；浏览器使用同源 cookie。UI 覆盖配置严格使用 APP_ORIGIN=http://localhost:8081。所有 task 路径为 `/api/v1/tasks`，兼容 Agent.md 的 DTO。

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

生产依赖：MySQL、Kafka、MongoDB；Redis 是可失效进度/不可变结果缓存。LAB_MODE=test/demo 才允许 SQLite+内存文档/总线，必须在界面/就绪响应标注其非真实集成性质。

## 运行与边界

- API: `uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000`。
- 迁移: `uv run python -m backend.migrate`；API 启动不自动建表。
- Worker: `uv run python -m backend.worker`；健康检查 `python -m backend.worker --healthcheck`。
- 首版 worker **单副本**，relay 不支持竞争领取；consumer 与 executor 分线程，长模型调用不阻塞 Kafka poll。
- 就绪正文：`{status,mode,model_mode,dependencies}`；生产检查 mysql/schema、mongo、kafka；test/demo 的 mongo/kafka 值为 `in_memory_test_adapter`。Redis 不作为关键就绪条件。
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

Kafka 启动显式建立开发用单分区、单副本的任务与DLQ主题；这不是生产高可用配置。relay/consumer/executor分线程，consumer持久化inbox后再提交该消息offset。原始幂等键按字节UTF-8摘要保存，大小写及尾空格不同即不同键。


## 受限单 Agent：具体响应契约

实现状态：运行时、真实组件与浏览器教学链路已验收，见[单Agent验收报告](AGENT_TEST_REPORT.md)；真实 provider 仅有独立接口连通性检查，尚未完成工具调用及全栈 live 验收；不能以脚本或 mock 替代。
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

协议拒绝多tool_calls、截断、空final、重复call_id或未知结束原因；合法单tool_calls伴随assistant辅助文本会忽略辅助文本而不是拒绝。异步总deadline可取消等待、响应超限停止读取，不代表provider端取消计费。每attempt最多6个provider请求，总计最多6×MAX_ATTEMPTS；默认3次attempt时18，不承诺只调用/计费一次。不新增schema/租约心跳，不改变Outbox/Inbox/fencing提交规则。
