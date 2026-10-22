# 配置说明：来源、默认值、秘密与生效边界

核对日期：2026-10-22。以 [`backend/config.py`](../backend/config.py)、[`.env.example`](../.env.example)、[`compose.yaml`](../compose.yaml) 和 [`backend/agent_provider.py`](../backend/agent_provider.py) 为准。本文是教学配置说明，不是生产部署或完整 live 模式验收。

## 1. 先区分三种配置入口

1. **Compose 的变量替换**：根目录 `.env` 和启动 Compose 的进程环境为 `${变量}` 提供值；同名进程环境可能覆盖 `.env`。默认 Compose 只引用四个数据库密码、`LAB_PORT`、`APP_ORIGIN`，**没有把整个 `.env` 作为 `env_file` 传给容器**。
2. **容器环境**：`compose.yaml` 的 `environment` 决定 API、Worker、迁移进程实际得到哪些变量。其 `LAB_MODE=production`、`MODEL_MODE=deterministic` 是固定值，不随 `.env` 的同名变量改变。
3. **直接启动 Python**：后端读取进程环境，不自动读取 `.env`。`Settings` 的默认值在 `backend.config` 导入时求值；改文件或再次 `Settings()` 都不会自动刷新已经导入的配置。不要 `source` 来历不明的 dotenv 文件，它不是可信 shell 脚本。

Compose 的变量替换、优先级与注释语法可参见 [官方说明](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)。本初始化器只支持下文的保守子集，并非完整 Compose dotenv 解析器。

`.env.example` 是字段示例，里面的 `replace-…` 不是安全密码；初始化器把任何非空占位符都视为已有值，**不会替换它们**。首次配置优先让初始化器创建文件，再按需编辑非秘密配置。默认 deterministic 教学链路不需要模型 Key。

### 已有本机栈的 `.env.compose.local`

本轮操作台**不新增环境变量、凭据、模型 Key 或外部服务**。已有 `.env` 中的模型配置保持不动；已采用独立 `.env.compose.local` 的本机栈继续通过 `--env-file .env.compose.local` 显式读取，文件受现有 `.env.*` 忽略规则保护，不提交、不输出、不由云端复制覆盖。初始化器的 `--path` 只接受名为 `.env` 的文件，不要拿它重建 `.env.compose.local` 或旋转已有数据库密码。

同一启动/迁移/停止流程必须使用相同 env-file、Compose 文件、project 和已有卷；换 project 可能得到新卷，不能把“空库启动成功”当旧数据升级成功。授权更新流程见[运维说明](OPERATIONS.md#组件操作台的保留数据更新)。本机更新仍待云端精确提交 CI 之后单独验收。

## 2. 开发凭据安全初始化

### 首次创建

前提：这是所有者批准配置的私有开发目录，尚无需要沿用凭据的已初始化数据卷。以下是供所有者以后执行的步骤；本轮云端开发只运行了隔离临时目录测试，没有操作用户电脑或真实 `.env`。

```bash
python scripts/infra-init-env.py
```

不存在 `.env` 时，生成四个独立随机密码（各 24 字节随机源、48 个十六进制字符）和 `LAB_PORT=8080`。密码适合直接用于当前 Compose 的连接 URL，不会输出值。默认调用遇到任何已有 `.env` 都拒绝，不读取、解析或重写其内容。

### 已有模型配置，但开发凭据尚未设置

**仅适用于四项数据库凭据尚未用于初始化相应服务的情况。** 先关闭编辑器写入、同步工具及其他初始化进程，再显式运行：

```bash
python scripts/infra-init-env.py --fill-missing
```

该选项只处理 `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`MONGO_PASSWORD`、`REDIS_PASSWORD`：

| 原状态 | 行为 |
|---|---|
| 键不存在 | 在文件末尾追加该键，不增加其他配置项 |
| `KEY=`、等号后只有空格/制表符、空单引号/双引号，或 `KEY= # comment`（注释前有空白） | 插入新随机值，保留已有引号、空白和注释 |
| 任意非空值，包括占位符、`0`、引号中的空格、`${OTHER}`、`KEY=#literal` 的值 | 逐字节保留，不判断它能否连接数据库，不展开变量、不旋转密码 |
| 四项都非空 | 验证后成功返回，不写文件、不生成新密码、不改变 inode 或权限 |
| `.env` 不存在 | 与首次创建相同 |

`MODEL_API_KEY` 和其他未知变量、注释、原有换行均按原始字节保留。支持 UTF-8、可选文件首 BOM、LF/CRLF（混用时也保留每行原样）；追加行使用已有首个换行风格，原末行无换行时只加必要的分隔换行。**保留 BOM 不代表所有第三方 dotenv 读取器都支持 BOM**；跨工具使用优先无 BOM UTF-8。

支持保守的单行 `KEY=value`、可选 `export`、单/双引号和行内注释。任意重复键（包括非数据库键）、未闭合引号、多行值、非 UTF-8、裸 CR、控制字符、超过 1 MiB、没有等号的行或其他不支持的语法均拒绝，原文件不变；不猜测、不执行、不整体解析后重新序列化。遇到复杂配置请由所有者在私有编辑器中逐项处理，勿将内容贴进问题报告。

### 已有数据库卷时，绝不能靠生成新密码“修好连接”

脚本不连接数据库，不能知道外部数据卷是否已初始化，也不能证明缺失的密码从未使用过。**如果卷已有数据，某个密码缺失/为空，应先找回原凭据或制定该服务的显式轮换方案；不要运行 `--fill-missing` 给它随机补值。** 修改 `.env` 不会自动修改已有 MySQL/MongoDB 用户密码；当前 Redis 密码还来自启动参数，单改文件也不改变正在运行的 Redis。数据库侧凭据和客户端配置必须协调变更。

初始化器不是密码轮换器、备份恢复器或数据重置工具。不要删除 `.env`、删除数据卷或重建数据库来绕过拒绝；任何真实本地凭据生成、轮换和启动都需要所有者另行批准，不属于本次云端任务。

### 文件安全和平台支持

| 平台/场景 | 当前行为与证据 |
|---|---|
| Linux 本地 POSIX 文件系统 | 已用私有临时目录进行功能与故障注入测试。父目录须归当前用户所有且不能被组/其他用户写入；目标须是当前用户所有、非符号链接、仅一个硬链接的普通文件。父目录本身不能是符号链接 |
| POSIX 新建 | `0600` 私有临时文件先写入并 `fsync`，再以不覆盖目标的原子链接发布；竞争创建的 `.env` 不会被覆盖 |
| POSIX 补齐 | 私有临时文件写好后复核原文件 inode、大小、时间、权限和内容，再同目录原子替换；结果权限为原权限与 `0600` 的交集（不会增加所有者权限，移除组/其他及特殊权限）。无需补齐时不会顺便修改原权限 |
| 原生 Windows 新建 | 保留 `O_EXCL` 排他新建，不覆盖已有文件；输出非秘密 ACL 警告。沿用目录 ACL，不调用 `icacls`、不擅自变更权限；**`0600` 不是 Windows ACL 保证**。此兼容分支直接新建写入，不承诺 POSIX 原子发布或中断后的完整文件；仅有 Linux 上模拟分支测试，未做原生 Windows 验收 |
| 原生 Windows 已有文件补齐 | 明确拒绝，已有文件保持不变，等待支持 ACL 保留的实现；由所有者私下手动补齐，或在其批准后于真正的 Linux 文件系统处理 |
| WSL、其他 POSIX、网络/共享盘 | WSL 必须使用 Linux 文件系统才适用 POSIX 权限前提，不能把 `/mnt/c`、`/mnt/d` 的 Windows 挂载视为已验证 ACL 保留。macOS、WSL 实机、网络盘及特殊安全标签/文件系统均未验收 |

Python 官方文档明确区分 Windows `chmod` 的只读标志与 POSIX 权限，并说明 POSIX 成功重命名的原子性；这不等于跨平台 ACL 或断电持久性保证。[`os.chmod`](https://docs.python.org/3.12/library/os.html#os.chmod) / [`os.replace`](https://docs.python.org/3.12/library/os.html#os.replace)

并发边界：`.env.init.lock` 排他锁只协调本脚本的调用；脚本还会拒绝已观测到的并发修改。**检查和替换之间无法用可移植标准库实现对任意外部写入者的原子比较交换**，因此必须先停止编辑器、同步程序等写入，并使用可信目录；不声称抵御同用户恶意程序、忽略锁的写入者或突然断电。

正常成功/失败会清理锁和临时文件；不会生成 `.bak` 秘密备份。POSIX 强制终止可能留下 `.env.init.lock` 与 `0600` 的 `.env.init-*.tmp`（写入前最终权限还可能更严格），这些名称受仓库 `.gitignore` 的 `.env.*` 规则保护。发现残留应先确认没有运行中初始化器，再由所有者处理确切残留文件，不自动破锁、不打印内容、不用宽泛通配符删除 `.env`。不要强制把任何 `.env.*` 加入 Git；自选目录也应自行保持同等私密和忽略规则。

测试/受控副本可显式指定路径，父目录必须已存在，目标文件名必须为 `.env`；这不会自动改变 Compose 使用的配置文件：

```bash
python scripts/infra-init-env.py --path ./private-sandbox/.env --fill-missing
```

## 3. Compose 输入表

“修改后动作”指完成必要批准与凭据协调之后的动作，不是授权自动执行。Compose 容器已创建后，仅 `docker compose restart` 不会重新注入新环境；应核对配置后通过 `docker compose up -d` 重建发生变更的服务。不需要删除卷。不要在公开终端/日志输出完整 `docker compose config`，它可能展开秘密；只校验可使用 `docker compose config --quiet`。

| 变量 | 默认 / 来源 | 秘密 | 实际读取与用途 | 修改后动作 |
|---|---|---|---|---|
| `MYSQL_PASSWORD` | 无默认；初始化器随机值；Compose 必填非空 | 是 | MySQL `lab` 用户初始化；拼入 API/Worker/migrate 的 `DATABASE_URL` | 已有卷先协调数据库用户轮换，再更新使用该 URL 的进程；仅改 `.env` 不轮换用户 |
| `MYSQL_ROOT_PASSWORD` | 无默认；初始化器随机值；Compose 必填非空 | 是 | MySQL root 初始化与健康检查；不传给 API/Worker | 同上；不能仅改健康检查密码而让实际用户仍用旧值 |
| `MONGO_PASSWORD` | 无默认；初始化器随机值；Compose 必填非空 | 是 | Mongo 开发 root 账户初始化、健康检查及共享 `MONGO_URL` | 已有卷先协调用户变更，再重建相应客户端与服务配置 |
| `REDIS_PASSWORD` | 无默认；初始化器随机值；Compose 必填非空 | 是 | Redis 启动 `--requirepass`、健康检查及共享 `REDIS_URL` | 协调 Redis 与 API/Worker 配置后重建；不是运行中自动旋转 |
| `LAB_PORT` | `8080`；生成文件也写入 `8080` | 否 | 主机 `127.0.0.1:<端口>` → API 容器 `8000` | 重建 API 端口映射；同时检查浏览器 `APP_ORIGIN` |
| `APP_ORIGIN` | `http://localhost:8080`；Compose 可替换 | 否 | 传入共享应用环境；API 对写请求校验 Origin | 重建 API；协议/主机/端口应与实际入口完全对应 |

默认 MySQL 数据库 `agentlab`、用户 `lab`，Mongo 开发用户名 `root`，容器内部服务地址和 Kafka 单节点配置均写在 `compose.yaml`，不是任意同名 `.env` 参数。数据库不默认映射到主机公网。单节点内网明文、开发 root 账户、loopback 入口都不能等同生产最小权限/TLS。

## 4. 后端进程环境表

以下“Python 默认”只适用于没有被进程环境覆盖的值；Compose 一栏说明默认文件实际传入什么。“重启”表示用更新后的环境创建新进程/容器，不是热加载。

| 变量 | Python 默认 / 允许值 | 默认 Compose 来源 | 秘密 | 读取入口 / 修改后动作 |
|---|---|---|---|---|
| `LAB_MODE` | `production`；仅 `production/test/demo` | 固定 `production` | 否 | `Settings` → `Runtime`；API/Worker/迁移重启。`production` 只选真实适配器，不代表生产安全；`test/demo` 使用进程内 Mongo/Kafka 替身，独立 Worker 拒绝这两种模式 |
| `DATABASE_URL` | `mysql+pymysql://lab:change-me@localhost:3306/agentlab`（占位，不是可用安全配置） | 根据 `MYSQL_PASSWORD` 拼出 `mysql:3306/agentlab` URL | 是，含凭据 | `Settings` → SQLAlchemy；API/Worker/迁移重启。SQLite 只允许显式 `test/demo` |
| `MONGO_URL` | `mongodb://localhost:27017` | 根据 `MONGO_PASSWORD` 拼出 Mongo root URL，`authSource=admin` | 通常是 | `Settings` → Mongo 适配器；API/Worker 重启 |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | 固定 `kafka:9092` | 否，地址可能私密 | `Settings` → Kafka producer/consumer；API/Worker 重启 |
| `REDIS_URL` | 空字符串；禁用原任务缓存，lab Redis 不可用 | 根据 `REDIS_PASSWORD` 拼出 `redis:6379/0` URL | 通常是 | `Settings` → `ProgressCache` 及独立 lab Redis 操作；API/Worker 重启。原任务缓存可降级；lab 操作返回 `redis_unavailable`，不伪造空值 |
| `APP_ORIGIN` | `http://localhost:8080` | 见上一表 | 否 | `Settings` → API Origin 校验；重启 API |
| `COOKIE_SECURE` | `false`；仅大小写不敏感的 `true` 为真 | 不传入，使用默认 | 否 | `Settings` → API session cookie；重启 API。HTTPS 部署须另行评审，不是在 HTTP 教学环境盲开此值 |
| `MODEL_MODE` | `deterministic`；仅 `deterministic/live` | **固定 `deterministic`** | 否 | API 创建任务时持久化模式；Worker 执行前校验任务模式与自身模式一致。两侧必须协调重启，不能把已有队列任务悄悄转换模式 |
| `ALLOW_LIVE_MODEL` | `false`；仅大小写不敏感的 `true` 为真 | 不传入，使用默认 | 否 | `Settings` → Worker `LiveController` 授权门；受控 live Worker 必须显式为真并重启；单独开关不够 |
| `LEASE_SECONDS` | `120`，须大于 0 | 不传入，使用默认 | 否 | `Settings` → Worker claim 租约；重启 Worker，仅新 claim 使用新值。Agent 另需 15 秒持久化余量，正数并不代表执行预算足够 |
| `MAX_ATTEMPTS` | `3`，允许 `1..100` | 不传入，使用默认 | 否 | `Settings` → Worker 失败/恢复；重启 Worker。指总尝试数，不是“额外重试 3 次”；增大可能增加真实模型费用 |
| `KAFKA_TOPIC` | `agent.tasks` | 不传入，使用默认 | 否 | `Settings` → Outbox 发送、Worker 订阅/建 topic；涉及已有事件/offset，须先制定迁移方案再协调 API/Worker |
| `KAFKA_DLQ_TOPIC` | `agent.tasks.dlq` | 不传入，使用默认 | 否 | `Settings` → DLQ Outbox/建 topic；同样需要协调已有工作，不是安全重放开关 |
| `MODEL_BASE_URL` | 空字符串 | **不传入** | 地址本身通常不是凭据，但可含私有路由信息 | Worker 构造每次 live 控制器时读取；要求 HTTPS、主机有效，无用户名/密码/query/fragment；代码追加 `/chat/completions`。需正确注入环境并重启 Worker |
| `MODEL_NAME` | 空字符串 | **不传入** | 否，可能暴露私有模型名 | 每次 live 控制器读取，非空；需具备所需工具调用协议的提供方模型；重启 Worker |
| `MODEL_API_KEY` | 空字符串 | **不传入** | **是** | 仅 Worker 的 live 控制器需要；不得给浏览器/前端构建、API 或 CI；使用批准的私密注入途径，更新容器环境后重启 Worker |

不应为了让进程“启动成功”而依赖占位数据库 URL。数据库凭据含特殊字符时，手动构造 URL 需正确编码；初始化器的十六进制输出避免这个问题，但不会自动修复已有 URL。

### Live 模式不是往 `.env` 加一个 Key

当前仓库默认 Compose、CI 均保持 deterministic。**即使 `.env` 写了 `MODEL_API_KEY`、`MODEL_MODE=live`、`ALLOW_LIVE_MODEL=true`，默认 Compose 仍不会启用 live。** 没有已交付、已验收的全栈 live opt-in overlay；本文也不通过示例偷偷启用调用。

将来另行授权的 live 配置至少要：API 与 Worker 都设置 `MODEL_MODE=live`，Worker 另外得到 `ALLOW_LIVE_MODEL=true`、正确 HTTPS 地址、模型名和私密 Key；Key 只给 Worker。还需处理已排队任务的模式一致性，再进行少量真实业务 smoke。现有独立连通性检查不等于工具协议、整栈提交或费用验收。

当前代码仍限制每次 provider 请求 `max_tokens=1024`、每个 attempt 最多 6 次决策/5 次只读工具调用、执行最多 60 秒（并受租约剩余时间减 15 秒限制）。这些不是新的 `.env` 可调旋钮，也不是调用次数、token usage 或账单保证；请求输入、提供方实际行为、响应丢失、网络超时和任务级最多 3 次尝试都可能产生额外/重复计费。没有接收到成功响应也不能推断没有收费。

## 5. 非环境变量参数与可选入口

| 位置 | 当前固定值 / 边界 |
|---|---|
| `backend/auth.py`、`backend/app.py` | Session 24 小时，cookie 名 `lab_session`，HttpOnly、SameSite=strict；无环境变量开启 MFA、找回或认证限流 |
| `backend/adapters.py` | Redis 进度/结果 TTL 300 秒；Redis 连接/读超时 1 秒；不是限流功能 |
| `backend/worker.py` | 原任务消费组 `agent-executors-v1`，手动提交 offset，`earliest`；单 relay/Worker 是当前支持边界；新增独立 lab consumer 不共用任务组 |
| `backend/lab_schema.py`、`backend/lab_adapters.py` | 固定 topic `agent.lab.messages.v1`、group `agent-lab-observer-v1`、Redis 前缀 `lab:kv:`、Mongo `agent_lab.lab_documents`；不是用户环境变量或 API 参数 |
| `backend/migrate.py` | schema 目标 v2，保留版本 1 并追加 2，新增 `lab_records`/`lab_kafka_messages`；与 HTTP API v1、Kafka envelope v1 分开 |
| `backend/agent.py`、`backend/agent_provider.py` | 上述决策/工具/时间预算；provider 30 秒客户端超时且不跟随重定向；更多 DTO/字节预算见 [单 Agent 契约](SINGLE_AGENT.md) |
| `compose.ui.yaml` | 可选网关主机 `127.0.0.1:8081`，API Origin 固定为 `http://localhost:8081`；`LAB_PORT` 不控制网关端口。未加载 overlay 时不启动 UI |
| `compose.test.yaml` / `tests/integration` | `TEST_BASE_URL` 是测试客户端地址，默认测试为 `http://localhost:8080`，容器测试使用 `http://api:8000`；不是后端监听地址 |
| `backend/faults.py` / `compose.fault-test.yaml` | `LAB_TEST_HOOKS`、`LAB_TEST_PAUSE_AT`、`LAB_TEST_TASK_ID`、`LAB_TEST_RUN_ID` 只属于显式隔离故障实验；正常启动不加载该 overlay。实现/真实验收状态及租约配置以 [故障实验](FAILURE_LABS.md) 为准，不能拿实验租约用于日常 Agent |
| `tests/judge/capture.py` | `JUDGE_COMMIT` 只标记已有证据采集的提交来源，不启用真实模型、不代表语义质量评分 |

lab 全部复用原账号登录，但教学数据本机共享，不新增 owner/tenant 配置或配额。接口预算（TTL 1..3600 秒、值 4096 UTF-8 字节、Mongo JSON 16 KiB/6 层/200 节点等）是固定校验，详见 [API 契约](API_CONTRACT.md)，不是可通过 `.env` 放宽的任意命令入口。

## 6. 验证与排错顺序

1. 先确认是 Compose 替换变量、容器环境还是直接 Python 环境的问题，不输出带密码的 URL 或完整环境。
2. 已有文件被默认拒绝是保护行为；先判断是否有已初始化卷，再决定只补空项还是恢复原凭据。重复/复杂语法、锁或链接拒绝都不应通过删文件绕过。
3. 检查 `LAB_PORT` 与 `APP_ORIGIN` 是否对应实际入口；UI overlay 有独立固定入口。仅修改 `.env` 未重建容器不会刷新进程环境。
4. 连接错误先核对凭据与真实服务一致；不要把修改开发密码当成无损重置。数据库和工具故障步骤见 [故障实验](FAILURE_LABS.md)，HTTP 主链路见 [API 契约](API_CONTRACT.md)。
5. 开发检查使用项目已安装依赖，初始化器用例只写 pytest 私有临时目录：

```bash
uv run ruff check scripts/infra-init-env.py backend tests/judge
uv run pytest backend/tests/test_env_initialization.py
uv run pytest backend/tests tests/judge/test_capture.py -m 'not integration'
```

单元测试覆盖 Linux 新建/补齐、默认拒绝、原字节保留、权限、链接/语法拒绝、幂等、并发检测、故障清理和无秘密输出；Windows 分支仅模拟，不冒充实机验证。这些测试不启动真实数据库、Docker 或模型 API；完整集成和发布证据以当前测试报告及对应 CI commit 为准。
