# 运维与排障：保留事实，再恢复服务

面向本地学习栈的后端操作手册，包含组件操作台 schema v2 增量更新；历史任务实验保留独立范围。先读 [模块契约](MODULE_CONTRACTS.md)、[配置说明](CONFIGURATION.md) 与 [故障实验](FAILURE_LABS.md)。目标是知道“哪里坏了、哪些数据仍可信、下一步如何验证”，不是一键重置一切。

**证据边界（2026-10-22）**：基线 `f36523fa` 的 [CI 39725461902](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39725461902) 通过真实 Compose 主链路与既有组件故障测试。历史学习型 v1 的安全配置补缺已通过隔离临时文件单元测试；MySQL 停机探针已在 `9f892c67` 的 [CI 39728628773](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39728628773) 完成真实五阶段验证及健康恢复。历史学习型 v1 状态见[开发清单](DEVELOPMENT_PLAN.md)，新 lab 范围见[冻结计划](COMPONENT_PLAYGROUND_PLAN.md)，实际发布/CI 以对应提交报告为准，不能沿用旧 CI 当作新增行为的证据。本文命令经过源码/官方语法核对，**本文新增备份恢复流程没有执行，恢复能力未验收**。历史精确 SIGKILL 窗口证据见[开发报告](DEVELOPMENT_REPORT.md)，不覆盖新 lab；独立 provider 连通性也不是完整 live 验收。

## 1. 操作前的最小清单

- 授权环境中的 Docker Engine/Desktop、Compose v2、Python 3；本页多行命令使用 Bash。容器 Python 与锁定依赖见 [Dockerfile.api](../Dockerfile.api)，不是要求在用户电脑另装一套服务。
- 先确认 Docker context 指向预期的**独立学习环境**。不要把远程 Docker context 当成本机；不要在真实用户数据上执行停库、故障或恢复实验。
- 默认 [compose.yaml](../compose.yaml) 启动 MySQL、Kafka、MongoDB、Redis、一次性 migrate、API、Worker。数据库不发布主机端口；API 仅绑定 loopback。UI 需显式 [UI 覆盖配置](UI_GUIDE.md)，不要混用两套 Origin。
- 默认 `MODEL_MODE=deterministic`；不要为了排障加入真实模型凭据、启用 live 或放大重试次数。`LAB_MODE=production` 只是选择真实适配器，不是上线认证。
- 保留足够磁盘、内存和下载空间，但项目没有实测的通用最低资源承诺。Docker 不可用就记录“真实实验未运行”，不能用 SQLite/内存替身代替。
- POSIX 配置助手要求本地 Linux 文件系统的权限/原子替换语义；WSL2 的 Linux 文件系统与 `/mnt/d` 等 Windows 挂载不是同一个安全假设。原生 Windows 的既有文件补缺目前拒绝执行，ACL 安全更新尚未验收；不要用 `chmod 600` 宣称 Windows ACL 已安全。

在仓库根目录做不打印秘密的预检：

```bash
python --version
docker version
docker compose version
docker context show
git status --short
```

确认环境后才继续。不要运行/分享完整 `env`、`printenv`、`docker inspect` 或 `docker compose config` 输出；它们可能包含秘密。配置结构验证使用 `docker compose config --quiet`。

## 2. 新建配置与保留既有 `.env` 是两条路径

入口是 [scripts/infra-init-env.py](../scripts/infra-init-env.py)，不是把示例密码直接用于数据库。

### 全新目录，没有 `.env`

```bash
python scripts/infra-init-env.py
docker compose config --quiet
```

助手只生成四项开发凭据与默认端口，不生成模型 key。排他新建失败时停止检查；不要为消除“已存在”提示删除 `.env`。POSIX 新文件权限为 `0600`；Windows 新建依赖目录继承 ACL，必须另行确认私密目录，不能把 POSIX mode 当作 ACL 保证。

### 已有 `.env`，例如先填了模型配置

默认命令保留原文件并拒绝覆盖。已具备完整开发凭据时直接校验配置，不需要重新生成。

历史学习型 v1 新增的显式补缺入口如下，已通过隔离临时文件单元测试；发布状态见开发清单，使用前确认所检出版本已包含该选项：

```bash
python scripts/infra-init-env.py --help
# 仅在私有本地 POSIX 文件系统，停止编辑器/其他写入者后：
python scripts/infra-init-env.py --fill-missing
docker compose config --quiet
```

- 只补四项必需开发凭据中缺失/明确空值的条目；保留已有非空值和不相关配置，不是密码轮换。占位词、空格字符串、变量引用不是自动可替换的空值。
- 重复键、含糊或不支持的 dotenv 语法、链接、非普通文件、权限/并发异常应拒绝；不要关闭检查或把私密配置贴进 Issue。修正时先私密保存原文件，只展示键名和脱敏错误。
- 若已有数据卷，缺失的密码可能只是配置丢了：**应找回原来匹配数据库的凭据，而不是生成新密码尝试连接**。MySQL/Mongo 初始化变量只对新数据目录生效，改 `.env` 不会同步改库内账户。
- 留下锁文件时先确定没有初始化进程仍在工作，再调查异常；不要一遇锁就删除、重跑。原生 Windows 既有文件补缺应保持停止，等待 ACL 安全实现或人工在受控工具中处理；不要迁移真实秘密来绕过门槛。

## 3. 启动、确认业务可用与非破坏性停止

下面使用单独的学习项目名，避免操作日常栈。首次实验前先核对该名字没有旧数据；若已有项目，不要误把它当全新。`COMPOSE_PROJECT_NAME` 会覆盖 Compose 文件中的默认名字，并传给后续测试脚本；此变量不是密码。[Compose 官方环境变量说明](https://docs.docker.com/compose/how-tos/environment-variables/envvars/)

```bash
export COMPOSE_PROJECT_NAME=agent-ops-learning
export LAB_PORT=18080
export APP_ORIGIN=http://localhost:18080
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml up -d --build --wait --wait-timeout 300
docker compose -f compose.yaml ps --all
curl -fsS http://localhost:18080/healthz
curl -fsS http://localhost:18080/readyz
```

`migrate` 成功退出是正常状态，不应强行让它常驻。启动超时不等于数据库损坏：先看具体服务、迁移日志、磁盘和依赖，不要删卷重来。

可用性要分两步：先看 readiness，再跑一个合成业务闭环：

```bash
# 会注册合成用户并写入合成任务，只能用于独立学习栈。
TEST_BASE_URL=http://localhost:18080 python scripts/test-http-smoke.py
# 更完整的真实故障实验会停止/恢复服务；独占这个项目后才运行。
bash scripts/test-integration.sh
```

HTTP smoke 不是完整权限/故障验收，也不验证真实模型。故障脚本必须沿用同一 `COMPOSE_PROJECT_NAME`；不能一边用 `-p` 启动 A，一边让脚本默认停止 B。不要同时在同一项目运行浏览器测试、故障脚本和手工任务。脚本退出后检查所有依赖与 Worker 已恢复，不仅看最后的 PASS 文本。

普通停止有两个层级：

```bash
# 停进程、保留容器和命名卷，之后可 start。
docker compose -f compose.yaml stop
docker compose -f compose.yaml start

# 移除本项目容器/网络，保留命名卷，之后用 up 重建。
docker compose -f compose.yaml down
```

若希望减少恢复时重复执行：先停止新的提交/测试，再停 API；保持 Worker 运行直到第 5 节检查确认任务都终态且 Outbox 无待发，最后停 Worker 和数据服务。停机期限内仍有任务时保留记录并按租约恢复，不能手动改成成功。当前 Worker 没有经过验收的业务排空协议，容器停止可能中断 attempt，外部模型调用仍可能重做。

**不要把 `down -v` / `down --volumes`、`docker volume prune` 或 `docker system prune --volumes` 用作普通停止或故障恢复。** CI 的一次性卷销毁是受控测试清理，不是日常运维范例。删卷须单独确认项目、数据归属、备份及不可恢复后果。[Compose down 官方说明](https://docs.docker.com/reference/cli/docker/compose/down/)

### 组件操作台的保留数据更新

**这是供协调者在授权本机环境执行的操作说明，不是本机已更新的记录。** 由协调者在新功能对应的云端完整 CI 通过后，核对用户本机目标提交、已有 project、Compose 文件、卷和忽略的 `.env.compose.local`，再更新同一栈。保留原 `.env`、模型配置、已有账号/任务及教学数据；不新建凭据，不启用 live，不复制云端配置，不删卷。

1. 核对目标 commit 和 CI 的真实迁移/组件/浏览器证据，不拿历史 `102491d2` 绿灯替代。先记录已有账号/任务及 lab 数据的最少非秘密基线；确定原数据卷归属和可接受的维护窗口。
2. 在原项目中构建应用镜像，停止新写入（包括其他浏览器/脚本），暂停 gateway/API/Worker；保留 MySQL/Kafka/Mongo/Redis 与原卷运行。不要以更换 project 或新建空库规避迁移。
3. 显式运行新版本 `python -m backend.migrate`，保留脱敏退出结果；**迁移失败就停止后续更新**。部分正确的 v2 DDL 可以验证后补齐；未知/冲突结构先诊断，不能改版本号/删表强行通过。
4. 迁移成功才重建 API/Worker/UI。核对 `/readyz`、版本集合 `{1,2}`、旧账号登录/任务所有权和旧结果，再按[四组件教程](COMPONENT_PLAYGROUND_GUIDE.md)做真实 smoke。
5. 记录目标提交、迁移输出、旧数据保留、真实四操作与浏览器结果。任何一项未做就写未完成；云端通过不是用户本机已更新。

下例只用于**已存在且已确认使用 `.env.compose.local` 的同一个本机栈**。先在当前终端将 `EXISTING_PROJECT` 设置为实际已核验的 Compose project；这里不提供默认值，以免误建另一组卷。数据库须已正常运行。示例仅做 shell 语法检查，未在本文编写环境执行 Docker 更新：

```bash
test -n "${EXISTING_PROJECT:-}" || { printf '%s\n' '先核对并设置已有 Compose project'; exit 1; }
test -f .env.compose.local || { printf '%s\n' '保留并核对原配置；不要生成替代凭据'; exit 1; }
LOCAL_DC=(docker compose -p "$EXISTING_PROJECT" --env-file .env.compose.local -f compose.yaml -f compose.ui.yaml)
"${LOCAL_DC[@]}" config --quiet || exit 1
"${LOCAL_DC[@]}" ps --all
"${LOCAL_DC[@]}" build api worker migrate gateway || exit 1
"${LOCAL_DC[@]}" stop gateway api worker || exit 1
"${LOCAL_DC[@]}" run --rm --no-deps migrate || { printf '%s\n' '迁移未通过；保留卷并诊断，不继续更新'; exit 1; }
# 已显式迁移且原数据依赖正常；不重建/删除数据服务。
"${LOCAL_DC[@]}" up -d --no-deps --wait --wait-timeout 300 api worker gateway || exit 1
curl -fsS http://localhost:8081/readyz
"${LOCAL_DC[@]}" ps --all
```

`--no-deps` 不是跳过迁移的捷径：这里只在上一步显式迁移成功、原依赖正常时使用。`readyz` 仍不能替代 Kafka 收取回执、Redis 实际到期或旧数据核验。回退代码前也必须先确认 schema/协议兼容，不自动删除 v2 表、改历史版本或恢复旧卷覆盖新数据。

## 4. 状态、健康、指标：各自只证明自己的范围

实现入口：[app.py](../backend/app.py)、[worker.py](../backend/worker.py)、[service.py](../backend/service.py)。

| 入口/现象 | 能证明什么 | 不能据此证明什么 |
|---|---|---|
| `/healthz` 200 | API 进程能响应 | SQL、消息、结果库或 Worker 可用 |
| `/readyz` 200 | SQL 版本集合 `{1,2}` 及必要表/索引结构校验通过、Mongo ping、Kafka broker 元数据可取 | Redis、真实 provider、每条消息/任务、全部跨库数据一致性 |
| `/readyz` 503 | 至少一个必需探针失败，响应显示依赖名 | 所有请求已被网关拒绝；代码没有全局自动摘流 |
| `mode=test/demo` | 明示使用内存 Mongo/Kafka 替身 | 真实四组件通过 |
| Compose `healthy` | 配置的健康命令最近成功 | 自动修复、数据一致性、任务正在推进；仅 unhealthy 不必然触发重启 |
| Worker `--healthcheck` | `/tmp/worker-heartbeat` 修改时间在 30 秒内 | executor/relay/recovery/lab observer 每个循环正常；该心跳仅由任务 consumer poll 主循环刷新 |
| `/metrics` | `lab_http_requests_total`、`lab_http_request_duration_seconds` 与客户端默认指标 | Outbox 长度、任务成功率、过期租约、完整 tracing/告警平台 |
| 原任务 202 / `pending` | SQL 事务已接受任务及 Outbox | Kafka 已投递、Agent 已执行 |
| `ready` / `running` | Inbox 已接受 / 当前 attempt 被领取 | 卡住不会超时；租约/fence 仍决定提交资格 |
| `retry_wait` / `failed` | 持久化退避 / 终态失败 | Kafka DLQ 已确认接收；需另看待发 Outbox |
| `succeeded` | SQL 已提交结果引用 | Mongo 现在一定可读；仍须读取结果，缓存也不能跳过 SQL 授权 |
| lab Kafka `acknowledged` | 已保存真实 producer callback 确认与元数据 | 消费者收到；要另查 `consumer.received` |
| lab Kafka `unconfirmed` | 尚无已保存的生产确认 | 消息绝未投递；同 ID 查询不重新发送 |
| lab Redis `exists:false` / `ttl_ms=-2` | 新读取时该 key 不存在 | Redis 不可用；后者是 503 错误 |

```bash
curl -fsS http://localhost:18080/metrics | grep '^lab_http_'
docker compose -f compose.yaml exec -T worker python -m backend.worker --healthcheck
```

`/events` 是 SQL 生命周期事件，`/attempts` 是尝试/租约结果，`/agent-steps` 只公开已提交成功结果的动作；都不是隐藏思维链，也不是跨服务 OpenTelemetry spans。任务 DTO 的 `progress` 是离散阶段提示，不是剩余时间或真实模型进度。

## 5. 只读 SQL：先查聚合，不把私人任务倒出来

数据库名 `agentlab`，表名见 [db.py](../backend/db.py)。下面使用库内开发账户的交互密码提示，不把密码放在命令参数里；禁止改成 `-p明文` 或复制含密码 URI。只在私有终端输入，不录屏。`MYSQL_HISTFILE=/dev/null` 避免保存 SQL 客户端历史。

```bash
docker compose -f compose.yaml exec mysql \
  env MYSQL_HISTFILE=/dev/null mysql --user=lab --password --database=agentlab
```

进入 MySQL 后执行以下**只读事务**；结束后 `exit`。所有时间字段为 UTC epoch 秒，使用 `UNIX_TIMESTAMP()` 比较，不依赖本地日期格式。

```sql
START TRANSACTION READ ONLY;
SELECT version FROM schema_version ORDER BY version;
SELECT status, COUNT(*) AS task_count FROM tasks GROUP BY status ORDER BY status;
SELECT event_type, COUNT(*) AS pending_count
FROM outbox WHERE sent_at IS NULL GROUP BY event_type;
SELECT COUNT(*) AS expired_running,
       COALESCE(MAX(UNIX_TIMESTAMP() - lease_until), 0) AS max_expired_seconds
FROM tasks WHERE status = 'running' AND lease_until <= UNIX_TIMESTAMP();
SELECT COUNT(*) AS due_retries FROM tasks
WHERE status = 'retry_wait' AND next_attempt_at <= UNIX_TIMESTAMP();
SELECT COUNT(*) AS unfinished_attempts FROM attempts WHERE finished_at IS NULL;
SELECT COUNT(*) AS succeeded_without_reference FROM tasks
WHERE status = 'succeeded' AND result_id IS NULL;
COMMIT;
```

解读方法：

- 当前 schema 版本应同时保留 1、2；只有 1 不满足新应用 readiness。不要改版本行掩盖迁移缺失。
- Outbox 无返回行表示待发数为零；非零可能是正常短暂排队。观察重复采样的趋势和 relay 错误，而不是马上删记录。当前 Outbox 没有独立 `created_at`，不要凭空写“精确最老待发年龄”指标。
- `expired_running>0` 应由 recovery 处理；默认租约 120 秒、最多 3 次尝试，但以当前配置为准。一直不下降时查 executor/recovery 与 SQL，**不要 `UPDATE tasks SET status=...` 绕过 fence**。
- `unfinished_attempts` 包含正在合法运行的工作；不能仅凭大于零判断坏数据。排空备份要求其为零。
- `succeeded_without_reference` 必须为零；即使为零，也只检查 SQL 引用存在，不证明 Mongo 文档存在。
- 数据库时钟与应用时钟偏差会影响租约诊断，先核对宿主/容器时钟；不要在运行任务时随意调时钟模拟恢复。
- 不要用 `SELECT * FROM users/sessions/tasks/outbox` 排障：包含哈希、prompt、事件材料。需要单个合成任务时只取明确列，使用有界条件；公共报告通常只需计数、错误码与脱敏 request_id。

## 6. 按模块定位，而不是依次重启所有服务

| 模块/症状 | 先查 | 正确恢复边界 |
|---|---|---|
| API 连接失败 / 404 | 项目、`ps --all`、loopback 端口；默认 API 入口不是前端；路由以 [API 契约](API_CONTRACT.md) 为准 | 修正入口/端口；不要为方便改成公网监听 |
| 401 / 403 / 409 / 422 | 会话是否过期、Origin、当前 CSRF、幂等键与原参数、输入限制；`/auth/me` 会刷新 CSRF | 同一次提交保持同键同参数；不要移除所有权/CSRF 或把 cookie 上传 Issue |
| MySQL down / 503 `database_unavailable` | MySQL 容器健康、迁移退出码、连接权限、磁盘；SQL 聚合在停库时当然不可用 | 恢复同一卷与匹配凭据后再探测。已缓存结果也必须 SQL 认证/授权，不允许离线缓存绕权。本轮 MySQL 停机证据见开发报告，不能用早期基线替代 |
| `pending` + 待发 Outbox | Kafka 元数据、relay 类型错误、MySQL 可写性 | Kafka 恢复后 relay 重发同 event_id；允许重复，不手动伪造 `sent_at` |
| Kafka 正常却 Worker 反复退出 | 消费解码/schema/未知 task 错误、消费组是否推进，见下一节 | 坏消息不能由重启自动变好；禁止跳 offset 或删 topic 掩盖 |
| `ready` 积压 / 过期租约不回收 | Worker executor 日志、SQL 连接、尝试结果、当前 lease；不要只看 consumer 心跳 | 先恢复依赖/执行循环，再观察 recovery。首版单 Worker/relay，没有租约续期或已验收的多副本扩容 |
| Mongo 停机 / 503 `document_unavailable` | Mongo 健康、结果缓存是否 miss、SQL committed reference 是否对应文档 | Mongo 写失败不能 SQL 成功；结果读取 miss 时应 503，不能返回假数据。旧 fence 孤儿文档不是可公开结果，不手工把其引用补到 SQL |
| Redis 停机 | `/results.cache_status=unavailable`、回源是否成功 | Redis 可丢弃，依赖 SQL 授权与 Mongo 正文；TTL 当前为 300 秒。readyz 不检查/列出 Redis；不是 readiness 的 degraded 字段 |
| Mongo down 但旧结果仍 200 | 是否已有不可变结果缓存命中；SQL 仍必须正常且已授权 | 缓存命中不证明 Mongo 恢复。不要清空整库来制造 miss；故障测试只操作合成任务的特定缓存键 |
| `failed` / Agent 预算或配置错误 | attempts 的 outcome、脱敏 error.code、API/Worker 模式是否匹配 | 有限重试是设计；不要无限增大次数、延长到过期租约外或启用 live“试一下”。失败任务没有现成安全重放管理 API |

故障恢复通常是恢复原来停止的服务，再检查依赖 readiness 和业务。例如在**确认所属项目的隔离实验**中恢复 MySQL：

```bash
docker compose -f compose.yaml up -d --no-deps --wait --wait-timeout 180 mysql
curl -fsS http://localhost:18080/readyz
docker compose -f compose.yaml ps --all
```

这不是“readyz 失败就重启 MySQL”的自动策略。迁移失败、权限错误、磁盘满、坏消息、正在进行的升级都需要各自诊断。恢复后使用原 task_id 和原幂等键观察，不反复提交新任务掩盖原任务丢失。

### 组件操作台的单独排障

| 现象 | 正确判断与下一步 |
|---|---|
| lab MySQL/Mongo 记录消失 | 数据本机共享，其他登录页可改单条；刷新/按 ID 查。合法 ID 不存在是 404，不是账号隔离 |
| Redis 503 `redis_unavailable` | 实验不能降级。恢复原 Redis 与匹配配置再读指定 key；不要当成已过期，也不要清全库缓存 |
| Redis TTL 归零但未得到新响应 | 仅浏览器估算，仍未确认到期。按「再次读取」；不可用时保留错误，不伪造 `-2` |
| Mongo 写后回读失败 | 返回 `document_unavailable`；写入可能已经发生，先查列表/ID，不用输入框冒充落库 |
| Kafka 未确认/响应丢失 | 保留发送前 UUID，GET 原 ID；同 ID 同内容 POST 也不会再发送，不能用新 ID 自动补发 |
| Kafka 已确认但尚未收取 | 核对原 Worker、lab observer 日志、SQL 可写性、固定组 `agent-lab-observer-v1`；短时轮询结束不等于丢失 |
| Kafka `unconfirmed + received` | 两种观察可以并存；消费回执证明实际收到，不手工补 ack 或重发 |
| MySQL v2 readiness 失败 | 先看显式迁移退出码和结构诊断；不得因版本 1 还存在就当 ready，也不删卷重来 |

只在独立合成环境做暂停 Worker/停 Redis/Mongo/Kafka 的故障实验，不在待保留的用户本机数据上随手试。恢复后分别检查真实读写/收取与原任务回归。lab observer 遇 SQL/offset 失败会关闭重建 consumer、从已提交位置重读；无效协议可拒绝回执并越过该无效记录。**下节毒消息说明针对原任务 consumer，不是 lab observer。**

### 原任务 Kafka poison message 的明确限制

[worker.py](../backend/worker.py) 关闭自动 commit/store；先解码并持久化 Inbox，再同步提交 offset。无效 JSON、不支持的 schema/type、未知 task 或 SQL 失败会使主循环退出，不应越过未持久化消息。Compose 可重启该进程，但相同毒消息可能再次阻塞；**任务执行失败的 DLQ 不等于消费者已有毒消息隔离机制**。

只读检查消费组（先验证工具存在，缺失就停，不临时安装）：

```bash
docker compose -f compose.yaml exec -T kafka \
  test -x /opt/kafka/bin/kafka-consumer-groups.sh
docker compose -f compose.yaml exec -T kafka \
  /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group agent-executors-v1 --describe
```

记录 topic/partition/offset、错误类型和代码版本；不要把原始消息正文公开。检查生产者 schema 与 SQL task 是否确实存在。需要修复解析或设计隔离/审计重放时进入开发修复流程，在合成消息上证明连续 offset 安全后再处理。当前没有通用人工恢复命令，**不提供 `--reset-offsets`、删 topic、删 Inbox/Outbox 或改数据库状态的“快捷修复”**。受控停 Worker 可避免重启噪声，但会一起停 relay/executor，必须记录影响与恢复条件。

## 7. 日志、文件系统、数据卷

### 安全日志

API 未知异常只记录 request_id/异常类型，Worker 循环记录类型，但第三方驱动和容器启动日志未必遵守相同规则。`infra-redact.py` 可辅助替换部分秘密/URI，**不是绝对脱敏器**：它不理解任意私人 prompt、cookie、CSRF、未知键名或所有 dotenv 表达式。先最小化采集，在本地人工复核再选取片段；不要把整个目录上传。

```bash
umask 077
mkdir -p .secrets/operations
chmod 700 .secrets/operations
docker compose -f compose.yaml ps --all > .secrets/operations/services.txt
docker compose -f compose.yaml logs --no-color --tail=100 api worker migrate 2>&1 \
  | python scripts/infra-redact.py > .secrets/operations/services.redacted.log
git check-ignore .secrets/operations/services.redacted.log
```

此日志助手会在本地读取 `.env` 以做替换，不应在没有读取该配置授权的环境运行。不要使用 `set -x`、HTTP verbose/trace 或记录完整请求头。测试报告仅发布明确白名单文件，排除 auth/outage JSON、浏览器 storageState、trace ZIP、备份和 `.env`。

### 卷与磁盘

默认命名卷映射：MySQL `/var/lib/mysql`、Kafka `/var/lib/kafka/data`、MongoDB `/data/db`、Redis `/data`。`down` 不删卷；换项目名会得到另一组卷，不等于原数据消失。容器可重建不意味着卷可随意清空。

```bash
df -h .
df -i .
docker system df
docker volume ls --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME"
docker compose -f compose.yaml stats --no-stream
```

`df` 只代表命令所在文件系统；Docker Desktop 的 VM 磁盘或远程 daemon 数据盘要在对应环境另查。不要为“修权限”递归 `chmod 777` 数据卷，不把正在写入的数据库目录直接复制称为一致备份。磁盘满时先停止新增流量、保留有限诊断、规划有把握的空间释放；不删除 WAL、binlog、Kafka segment 或 Mongo 文件。

## 8. 备份与恢复学习演练 — **未执行 / 未验收**

本节是经源码与官方命令语法核对的分阶段操作设计，**不是已经跑通的备份脚本，也不是灾备承诺**。任何前置条件不满足就停止对应阶段；不得通过安装新工具、改权限、覆盖旧库或跳消息去凑成功。

### 8.1 演练范围与不可恢复部分

**范围仍是旧任务/结果，不是 lab 全数据恢复方案**：本节 Mongo 导出只包含 `agent_lab.results`，不包含 `lab_documents`；不会恢复 Redis 教学键或 Kafka 原消息。若源中已有须保留的 lab 数据，停止使用本节流程，先另行设计并验收完整备份。不要把 MySQL 中恢复出的历史 receipt 当成恢复了 broker 消息。

仅允许第 3 节的独立 synthetic 项目，且没有需保留的 lab 数据：停止新提交，所有任务已 `succeeded/failed`、无未结束 attempt、无待发 Outbox，并确认已创建事件进入 Inbox。只恢复 **MySQL 中已经提交的终态记录及其 Mongo 结果**。

**MySQL + Mongo 导出不会自动恢复 Kafka 历史、消费组 offset、DLQ 消息、在途交付或 Redis 缓存。** 本演练创建空 Kafka/Redis 卷；失败终态保留 SQL 记录，但不重新生成丢失的 DLQ 历史。任何非终态/待发工作都不在本演练保障范围，不能在恢复端启动 Worker“碰运气继续跑”。这不是跨库分布式快照，也不覆盖在线写入、时间点恢复、HA、RPO/RTO 或真实模型去重计费。

备份含 prompt、结果、用户密码哈希和会话/CSRF 哈希。即使数据是合成的也应私密保存、限制权限、按需加密，**不上传 GitHub/CI 附件/公共云链接**。`.gitignore` 忽略只是防误提交，不是加密或访问控制。

### 8.2 准备与冻结源数据

在同一 Bash 会话、仓库根目录设置两个不同项目；这里 `SRC` 必须确实是你刚建立的独立合成环境，不是把现有私有栈改名：

```bash
SRC=agent-ops-learning
DST="agent-ops-restore-$(date -u +%Y%m%d%H%M%S)"
test "$SRC" != "$DST" || exit 1
SRC_DC=(docker compose -p "$SRC" --env-file .env -f compose.yaml)
umask 077
mkdir -p .secrets/operations
chmod 700 .secrets/operations
BACKUP=$(mktemp -d "$PWD/.secrets/operations/snapshot.XXXXXX")
git check-ignore "$BACKUP" || exit 1
git rev-parse HEAD > "$BACKUP/commit.txt"
"${SRC_DC[@]}" ps --all
```

在停 API 前，按 [curl 合成闭环](FAILURE_LABS.md) 在 `http://localhost:18080` 创建一个已成功的合成任务，并保留该次合成登录 JSON 和 task_id 作恢复验证。该示例中的 `BASE` 要改成这个学习端口；在退出会话触发临时文件清理前，把它的 `$TMP_LAB/register.json` 复制到 `$BACKUP/synthetic-login.json`（权限 `0600`），不是复制真实用户凭据或旧 session cookie。HTTP smoke 单独通过不一定保留可重新登录的用户名，因此不能省略这一步。

```bash
# 仅复制上一步生成的合成帐号文件；变量不存在就停止，不猜路径。
test -n "${TMP_LAB:-}" && test -f "$TMP_LAB/register.json" || exit 1
cp "$TMP_LAB/register.json" "$BACKUP/synthetic-login.json"
chmod 600 "$BACKUP/synthetic-login.json"
# 终止测试/其他写入者后，关闭新提交入口；Worker 暂时继续排空。
"${SRC_DC[@]}" stop api
```

在源 MySQL 用第 5 节的交互连接，反复做只读聚合，直到以下条件均为零；不要在一条未结束事务里一直轮询旧快照：

```sql
START TRANSACTION READ ONLY;
SELECT COUNT(*) AS nonterminal FROM tasks WHERE status NOT IN ('succeeded', 'failed');
SELECT COUNT(*) AS pending_outbox FROM outbox WHERE sent_at IS NULL;
SELECT COUNT(*) AS unfinished_attempts FROM attempts WHERE finished_at IS NULL;
SELECT COUNT(*) AS created_not_received FROM outbox AS o
LEFT JOIN inbox AS i ON i.event_id = o.id
WHERE o.event_type = 'task.created' AND i.event_id IS NULL;
SELECT COUNT(*) AS non_innodb FROM information_schema.tables
WHERE table_schema = 'agentlab' AND table_type = 'BASE TABLE' AND engine <> 'InnoDB';
COMMIT;
```

还须至少有一条成功的合成任务，否则没有结果可验。用第 6 节只读消费组命令确认任务 topic 的 lag 为零；它不是所有 DLQ 已消费的证明。排空无法完成时停止本次备份演练，转排障，不改状态、删消息或把等待缩成假成功。

然后 `"${SRC_DC[@]}" stop worker`，再次核对上述聚合全零。确认没有其他 writer、DDL 或管理操作。源 API/Worker 在两份导出完成前保持停止，MySQL/Mongo 保持运行。这种受控停写降低本次教学演练的跨库时间差，不推广为普遍一致性保证。

### 8.3 检查工具、导出私密副本

不要假定 pinned 镜像一定包含工具或功能。先执行可用性/版本检查；缺失/版本不兼容时记录阻塞并停止，**不要当场安装软件**：

```bash
"${SRC_DC[@]}" exec -T mysql sh -c 'command -v mysqldump && command -v mysql && mysqldump --version'
"${SRC_DC[@]}" exec -T mongo sh -c 'command -v mongodump && command -v mongorestore && command -v mongosh && mongodump --version && mongorestore --version'
```

下列命令保留交互终端供密码提示，密码不在 argv 中。MySQL 输入源 `lab` 密码；Mongo 输入源管理账户密码，权限边界仍是开发配置，不是生产最小权限方案。**不要用 `-T` 做交互密码输入，也不要把二进制 archive 经过 TTY 输出重定向**；归档写容器内私密临时文件后再复制。

```bash
"${SRC_DC[@]}" exec mysql sh -c 'umask 077; test ! -e /tmp/ops-agentlab.sql && mysqldump --user=lab --password --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF --skip-add-drop-table agentlab > /tmp/ops-agentlab.sql'
"${SRC_DC[@]}" exec mongo sh -c 'umask 077; test ! -e /tmp/ops-results.archive.gz && mongodump --username=root --authenticationDatabase=admin --db=agent_lab --collection=results --archive=/tmp/ops-results.archive.gz --gzip'
```

每个命令单独确认退出码为零；失败产生的部分文件不能当有效备份。固定临时文件名已存在时停止调查，不覆盖。MySQL 的 `--single-transaction` 适用于 InnoDB 且期间不能改表；本例不导出账户系统库、不保存 GTID 恢复状态、不生成删表语句。[MySQL 8.4 mysqldump](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html)

Mongo 只导出实际集合 `agent_lab.results`，使用 archive/gzip；未指定密码时用户名认证触发交互提示。本例 standalone 不使用副本集 oplog 方案。[MongoDB mongodump](https://www.mongodb.com/docs/database-tools/mongodump/)

```bash
"${SRC_DC[@]}" cp mysql:/tmp/ops-agentlab.sql "$BACKUP/agentlab.sql"
"${SRC_DC[@]}" cp mongo:/tmp/ops-results.archive.gz "$BACKUP/results.archive.gz"
chmod 600 "$BACKUP/agentlab.sql" "$BACKUP/results.archive.gz"
test -s "$BACKUP/agentlab.sql" && test -s "$BACKUP/results.archive.gz"
(cd "$BACKUP" && sha256sum agentlab.sql results.archive.gz > SHA256SUMS)
(cd "$BACKUP" && sha256sum -c SHA256SUMS)
```

大小非零、校验和一致只证明文件存在/未变，不证明可恢复。若主机缺 `sha256sum`，先记录工具缺失并停止该阶段，使用经确认的等价校验工具后再继续，不跳过校验。

### 8.4 先记录源结果，再恢复至全新目标

在源 MySQL 执行以下受限查询，把**合成数据**结果私密保存作基线，不贴到公共报告：

```sql
SELECT id, attempt_id, result_id FROM tasks WHERE status = 'succeeded' ORDER BY id;
SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY status;
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM attempts;
SELECT COUNT(*) FROM task_events;
SELECT COUNT(*) FROM outbox;
SELECT COUNT(*) FROM inbox;
```

逐个成功引用核对 Mongo，而不是仅比较两个库的总行数。在源容器交互连接：

```bash
"${SRC_DC[@]}" exec mongo mongosh --quiet --username root --authenticationDatabase admin
```

`mongosh` 会在交互终端提示密码且不回显；不要改成明文参数。[MongoDB Shell 认证连接说明](https://www.mongodb.com/docs/mongodb-shell/connect/)

在 mongosh 内将下列占位符替换为**本次合成 SQL 查询**的值；没有值就停止，不用陌生 UUID：

```javascript
use agent_lab
db.results.countDocuments({})
db.results.findOne(
  { _id: "<SQL result_id>" },
  { _id: 1, task_id: 1, attempt_id: 1, model_mode: 1, execution_kind: 1, controller_mode: 1, content: 1, steps: 1 }
)
```

每个成功引用必须存在，`task_id`、`attempt_id` 与 SQL 对应；本次新建任务应是 deterministic/scripted_test。私密记录该投影的内容/步骤以便恢复后逐项比较。Mongo 总数可能多于 SQL 成功数，因为存在旧 attempt 孤儿；不要因此删除文档，也不要把多出的文档认作成功任务。

新建目标私有配置，使用新凭据，不复制源 `.env`。`--path` 为既有安全初始化入口，先确认该版本已通过相应测试；目标目录也须在原生 POSIX 文件系统：

```bash
DST_DIR=$(mktemp -d "$PWD/.secrets/operations/restore.XXXXXX")
DST_ENV="$DST_DIR/.env"
python scripts/infra-init-env.py --path "$DST_ENV"
DST_DC=(env -u MYSQL_PASSWORD -u MYSQL_ROOT_PASSWORD -u MONGO_PASSWORD -u REDIS_PASSWORD LAB_PORT=18081 APP_ORIGIN=http://localhost:18081 docker compose -p "$DST" --env-file "$DST_ENV" -f compose.yaml)

# 两条输出都必须为空；非空就停止，换一个新的目标，而不是覆盖。
docker ps -aq --filter "label=com.docker.compose.project=$DST"
docker volume ls -q --filter "label=com.docker.compose.project=$DST"
"${DST_DC[@]}" config --quiet
"${DST_DC[@]}" up -d --wait --wait-timeout 180 mysql mongo
```

尚不启动 migrate/API/Worker；目标必须是新项目的**新卷**，不能有 external/shared volume 覆盖。核对目标 MySQL/Mongo 容器所挂载卷名属于 `$DST`，与源卷不同。只取挂载名称等最少字段，不打印完整 inspect：

```bash
docker inspect --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}' "$("${DST_DC[@]}" ps -q mysql)"
docker inspect --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}' "$("${DST_DC[@]}" ps -q mongo)"
```

目标命令的 `env -u` 只排除当前 shell 中可能覆盖新 dotenv 的四个密码变量，不打印或修改源配置。在目标重复工具检查；交互进入目标库确认 `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='agentlab';` 为零、Mongo `agent_lab.results` 的 `countDocuments({})` 为零。不为获得零值删除任何表/集合。已存在数据就停止，保留目标供诊断，另建一次性目标。

```bash
(cd "$BACKUP" && sha256sum -c SHA256SUMS)
"${DST_DC[@]}" cp "$BACKUP/agentlab.sql" mysql:/tmp/ops-agentlab.sql
"${DST_DC[@]}" cp "$BACKUP/results.archive.gz" mongo:/tmp/ops-results.archive.gz
"${DST_DC[@]}" exec mysql chmod 600 /tmp/ops-agentlab.sql
"${DST_DC[@]}" exec mongo chmod 600 /tmp/ops-results.archive.gz
# 输入目标的新 lab 密码；导入只针对 agentlab。
"${DST_DC[@]}" exec mysql sh -c 'mysql --user=lab --password --database=agentlab < /tmp/ops-agentlab.sql'
# 输入目标的新 Mongo 管理密码；没有 --drop，遇错误就停止。
"${DST_DC[@]}" exec mongo mongorestore --username=root --authenticationDatabase=admin \
  --archive=/tmp/ops-results.archive.gz --gzip --nsInclude='agent_lab.results' --stopOnError
```

SQL dump 没用 `--databases`，因此导入时显式选择新建的 `agentlab`。[MySQL SQL-format 恢复](https://dev.mysql.com/doc/refman/8.4/en/reloading-sql-format-dumps.html) Mongo 恢复与源使用相同版本镜像/兼容 Database Tools；`--stopOnError` 防止遇到重复键/验证错误后继续掩盖失败。[MongoDB mongorestore](https://www.mongodb.com/docs/database-tools/mongorestore/)

如果导入失败，停止验收、记录退出码和脱敏类型；**不要在同一部分恢复库里反复导入或加入 `--drop/--force`**。保留源不变，修正方案后使用另一组新目标卷重试。

### 8.5 恢复核验、业务读取与结束条件

必须逐项通过，不能只以“命令返回 0”宣称恢复成功：

1. 导入后版本集合与源私密基线一致；当前 v2 源应为 `{1,2}`。若是历史 `{1}` 备份，还必须单独执行并核验显式 v1→v2 后才能启动新 API。任务状态、users/attempts/events/outbox/inbox 计数与源基线一致；非终态/未结束 attempt/待发 Outbox/created 未入 Inbox 均为零。
2. **所有** SQL 成功 `result_id` 都能在目标 Mongo 读取；task_id/attempt_id、元数据、正文及步骤与源私密基线一致。小规模合成演练逐条核对，不仅抽查一个或只比数量。
3. 启动空 Kafka/Redis 和 API，但**不启动 Worker**。导入已带 schema；运行 migrate 验证当前 v2，或对合规历史 v1 执行显式增量。下面命令本身不能证明旧数据保留；仍须逐项核验，也不能替代本轮独立真实迁移测试：

   ```bash
   "${DST_DC[@]}" up -d --wait --wait-timeout 180 kafka redis
   "${DST_DC[@]}" run --rm --no-deps migrate
   "${DST_DC[@]}" up -d --no-deps --wait --wait-timeout 180 api
   curl -fsS http://localhost:18081/readyz
   ```

4. 在目标 API 使用源演练的合成账户**重新登录**，不要复制旧 session cookie。下面的 `TASK_ID` 必须仍是源演练保存的合成 task_id；只读请求不需要把 CSRF 放进命令行。首次结果读取应从空 Redis 回源，之后可 hit，再读取 agent-steps 并比较。用另一合成用户验证越权仍被拒。不要执行会新建任务并等待 Worker 的完整 smoke，或把“能新建任务”代替旧结果恢复核验。

   ```bash
   test -n "${TASK_ID:-}" || exit 1
   curl -fsS -c "$BACKUP/restored.cookies" -H 'Content-Type: application/json' \
     --data-binary @"$BACKUP/synthetic-login.json" \
     http://localhost:18081/api/v1/auth/login > "$BACKUP/restored-auth.json"
   curl -fsS -b "$BACKUP/restored.cookies" \
     "http://localhost:18081/api/v1/tasks/$TASK_ID/results" > "$BACKUP/restored-result.json"
   curl -fsS -b "$BACKUP/restored.cookies" \
     "http://localhost:18081/api/v1/tasks/$TASK_ID/agent-steps" > "$BACKUP/restored-steps.json"
   ```

5. 记录 commit、镜像/工具版本、导出与恢复时间、聚合计数、每个引用比较结果、退出码、未覆盖范围及源服务是否恢复。公开报告只发布脱敏结论；私密备份和基线不上传。即使全通过，也只能称“该版本、该合成终态数据集的已提交结果恢复演练通过”。
6. 删除容器内本次演练的两份临时导出文件，保留或按既定私密保留期清理主机备份；不用通配符删除其他文件。源可以按原配置 `"${SRC_DC[@]}" start api worker` 恢复，再查 readiness/ps。目标用 `"${DST_DC[@]}" down` 停止并保留卷；若要最终删除一次性目标卷，必须另行确认准确项目及不再需要的数据，不提供自动删卷步骤。

**当前记录：未执行以上导出、导入、逐引用/API 检查，未验收恢复能力。** 文档完整或链接可访问不能改变这条状态。

## 9. schema、依赖升级与回退的边界

当前 [migrate.py](../backend/migrate.py) 是明确的 **v1→v2 加法迁移**，不是对扩大后的 metadata 调用 `create_all` 冒充升级。全新库按冻结原表集合初始化 v1，再加 v2；已有 `{1}` 验证原结构后增加 `lab_records`、`lab_kafka_messages` 与固定索引，最后追加版本 2。原账号、会话、任务、Outbox/Inbox、attempts/events 不迁走、不改 owner，不删除版本 1。

允许入口状态为全新空库、合规 `{1}`、合规 `{1,2}`。未知未来版本、缺 v1 的 v2、没有合法版本历史的旧表或冲突结构，在自动变更前拒绝。MySQL DDL 有隐式提交：正确的部分 v2 对象可验证后补齐，但不能声称整个升级可由一个事务回滚。v2 版本标记也必须与表、列类型/可空性、主键、索引/唯一约束相符；重复迁移无数据改变。API readiness 和 Worker 启动都要求当前结构。

**只支持这条显式两版本路径，没有通用升级平台、自动降级或 down migration**。真实 v1→v2 的兼容证据须使用冻结 v1 和旧合成数据，而不是用最新 metadata 创建“假 v1”。迁移测试通过也不证明备份恢复、数据库大版本回退、HA 或灾备。HTTP `/api/v1` 与 Kafka envelope `schema_version:1` 没有因此变为 v2。

| 变更 | 安全起点 | 不能做的“回退” |
|---|---|---|
| 仅代码/依赖，schema/文档协议未变 | 单独分支、小步更新、重新锁定；离线测试后跑隔离真实集成/适用 UI；记录可用旧镜像与 commit | 只改 tag 就假设相同卷可安全运行旧代码 |
| SQL 表结构/数据语义 | 本轮仅支持显式 v1→v2；未来继续追加迁移及旧数据/失败恢复测试，先做适用备份与隔离演练 | 修改冻结 v1、手改版本行或删 v2 表冒充降级 |
| Mongo 文档或 Kafka 事件格式 | 保留旧 reader/consumer 兼容，按契约处理 schema version；验证回放与旧结果 | 修改消费者后跳过无法识别消息；把旧文档伪装成新 Agent 轨迹 |
| MySQL/Mongo/Kafka/Redis 大版本 | 阅读对应官方升级/降级约束，在复制的合成数据上演练；锁定已验收镜像 | 用旧数据库二进制直接打开新版本改写过的卷 |
| 密码变更 | 分别更新库内账户与应用配置，验证新连接，再按计划撤旧 | 只覆盖 `.env`、生成新密码、删卷“让它生效” |

源文件包括 [pyproject.toml](../pyproject.toml)、[uv.lock](../uv.lock)、[compose.yaml](../compose.yaml)、[Dockerfile.api](../Dockerfile.api)；前端/浏览器另有各自 lock。固定 tag 不是 immutable digest，也不等于最新/无漏洞。不要边排故边做未经测试的批量升级。

在已有锁定环境中的回归入口：

```bash
uv sync --frozen
uv run ruff check backend tests/judge
uv run pytest backend/tests tests/judge/test_capture.py -m 'not integration'
# 真实实验仍需第 3 节的独立栈，且会暂停/恢复组件。
bash scripts/test-integration.sh
```

`uv sync` 会同步本地依赖，需在获授权的开发环境执行，不在排障现场擅自安装。测试失败保留证据，区分单元通过、Compose 未运行、精确窗口未验收、live 未启用；不能用旧提交绿色 CI 宣称新版本已可回退。

## 10. 每次操作的结束检查

- [ ] 确认操作的是预期环境/项目，合成数据没有混入真实用户材料。
- [ ] 必需依赖与 API readiness 恢复，Worker 不仅心跳新鲜，原任务也有预期终态/合理重试记录。
- [ ] 没有手改状态、跳 offset、删卷或用缓存绕过 SQL 授权；遗留问题明确记录。
- [ ] 写明通过 / 失败 / 未运行，保留对应 commit 与最少脱敏证据。
- [ ] 没有公开 cookie、CSRF、模型 key、数据库密码、哈希、私人 prompt、备份或完整配置。
- [ ] 恢复/升级类演练逐项达到本页规定的验收，未达到的继续标未验收，不把手册当运行证明。

官方命令参考已于 2026-10-22 核对；运行时仍以实际 pinned 镜像中的工具版本和对应官方支持范围为准。
