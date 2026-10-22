# 冻结的首轮 API 契约

内部端口 8000，网关端口 8080；同源浏览器 cookie；所有 task 路径为 `/api/v1/tasks`，兼容 Agent.md 的 DTO。

- POST `/api/v1/auth/register` 或 `/api/v1/auth/login`: `{username,password}`；返回 `{user:{id,username},csrf_token}` 并设置 HttpOnly `lab_session` cookie。
- GET `/api/v1/auth/me`: `{user:{id,username},csrf_token}`；会话失效 401。
- POST `/api/v1/auth/logout`: 需 `X-CSRF-Token`；204。
- 所有已登录写操作需 `X-CSRF-Token`；若有 Origin 则必须匹配 APP_ORIGIN。首次注册/登录也校验 Origin。CSRF token 内存保存；刷新通过 me 获取轮换的 CSRF token。
- POST `/api/v1/tasks`: `{prompt}`，需 `Idempotency-Key`（1..128），202 Task。
- GET `/api/v1/tasks?limit=20&offset=0`: `{items,total,limit,offset}`。
- GET `/api/v1/tasks/{id}`: Task。
- GET `/api/v1/tasks/{id}/events`: `{items:Step[]}`。
- GET `/api/v1/tasks/{id}/results`: `{task_id,content,model_mode,cache_status}`；尚未成功 409。
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

MongoDB 选择/连接超时2秒、socket3秒、操作预算5秒；PyMySQL connect3/read5/write5秒。模型 HTTP 超时为每I/O30秒，不宣称整个任务强制截止时间。首轮未实现跨attempt结果复用；遗留文档只可能成为孤儿，不允许旧fence更新SQL成功。外部调用可能重复。

Kafka 启动显式建立开发用单分区、单副本的任务与DLQ主题；这不是生产高可用配置。relay/consumer/executor分线程，consumer持久化inbox后再提交该消息offset。原始幂等键按字节UTF-8摘要保存，大小写及尾空格不同即不同键。
