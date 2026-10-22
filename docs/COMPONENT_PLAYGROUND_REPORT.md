# 组件操作台：实施与验收记录

更新：2026-10-22。**云端代码、真实 CI 与本机升级均已验收；PLAY-01..07 已完成。** 本轮代码为 [`ec1126d27ee63bb401d29bb8705a11603a61e01c`](https://github.com/kismetcccc/agent-stack-lab/commit/ec1126d27ee63bb401d29bb8705a11603a61e01c)，[CI 39743833797](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39743833797) 三个 job 均为 `success`。本报告不把旧版绿灯、测试收集或模拟响应算作新功能真实验收。

## 1. 本轮交付与边界

- 计划先发布：`0f306a777655fffa1077703c7321f004a6a14921`，见[计划与契约](COMPONENT_PLAYGROUND_PLAN.md)。本轮只更新其状态，不重开历史学习型 v1。
- 主入口直接操作 MySQL CRUD、Redis KV/真实 TTL、Mongo JSON CRUD、Kafka 发送与真实消费者回执；无需创建 Agent 任务。点击步骤见[操作台教程](COMPONENT_PLAYGROUND_GUIDE.md)。
- 个人本机共享 lab 数据，不增加账号/租户隔离。保留登录、CSRF、Origin 和旧任务所有权；教学数据与账号、任务、结果分开。
- HTTP API 仍 v1，MySQL schema 是 v2，Kafka 教学 envelope 是 version 1。显式 v1→v2 不等于通用降级、备份恢复或高可用。
- 固定操作/命名空间，无任意数据库命令、Kafka 管理、全局清库或真实模型调用；不更改模型 Key，不扩展许可证、live、Kubernetes 或灾备范围。

改动集中在后端 `lab_api/lab_schema/lab_service/lab_adapters/lab_worker`、显式迁移与原 Runtime/Worker 接入、前端四个直接操作页、真实集成/浏览器及 CI、接口/教程/运维文档。准确文件差异以本轮提交及其历史为准，不能由本报告推断没有列出的部署动作已经执行。

## 2. 精确提交的云端验收

执行环境是 GitHub Actions 的独立 Linux runner：后端检查及 Compose 使用 Ubuntu 24.04，浏览器 job 使用 Ubuntu 22.04、真实 Chromium 和同源 8081 网关。测试使用临时合成数据；默认 deterministic，不调用真实 provider。

| 层级 | 已执行结果 | 证据与解释 |
|---|---|---|
| 后端/API/采集器 | **595 项通过**，Ruff 通过 | `checks`；`unit-evidence` 的 `unit.xml`：595 tests、0 failure/error/skip。离线 SQLite/显式替身测试不计真实组件 |
| 前端 | **58 项单元通过**；typecheck、production build 通过 | 计数来自成功 job 日志，不是 XML；Vitest/JSDOM 仍不是实际浏览器证据 |
| 真实 MySQL/Redis/Mongo/Kafka | **20 项 pytest 通过**，含独立升级与启动后保留验证 | `integration.xml` 16 + `recovery.xml` 2 + `schema-upgrade.xml` 1 + `schema-upgrade-http.xml` 1；实际容器 |
| 实际浏览器 | **38 项通过**，桌面与手机 | `test-results/browser.xml`：19 桌面 + 19 手机、0 failure/error/skip；原 30 + 新增 8 个组件旅程。竞态拦截不冒充真实宕机 |
| 迁移、故障与重启 | 冻结 v1→v2、旧数据保留、重复迁移、部分 DDL/版本冲突拒绝、依赖恢复和重启验证通过 | `compose-real-integration-evidence` 及相应 job 步骤；不推导备份恢复/HA |
| 原链路回归 | HTTP 主功能 smoke、既有故障恢复、四个精确 SIGKILL 窗口及无 hook 恢复通过 | `mysql-outage.xml` 1 项宿主故障探针、`crash-windows.xml` 4 项宿主探针另列，不加进上述 20 项 pytest |
| 图像与布局 | 修正后的桌面/手机 Mongo、Kafka 截图已完成人工视觉复核；几何检查通过 | 不是仅从测试退出码推断视觉正确；缺陷与修复见下节 |

三个实际 job：[`checks`](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39743833797/job/119707300326)、[`compose-integration`](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39743833797/job/119707547036)、[`frontend-browser`](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39743833797/job/119707299670)。旧 `102491d2` 的 409/13/30/30 仍只属于历史学习型 v1，不改称本轮结果。

### 已验证的功能事实

- **MySQL 与迁移**：使用冻结 v1 schema 和合成旧账号/会话/任务等数据升级；旧 v1 不 ready；新增两张 lab 表，保留版本 1 再追加 2。真实 DDL 边界注入中断（不是 SIGKILL）、额外 UNIQUE(name) 冲突拒绝、保留 marker 1 与旧行、补齐/重复迁移至 `{1,2}`、未来版本 999 拒绝及原认证/任务所有权保留均有验证；旧行与 SHOW CREATE 对照保留。
- **共享 CRUD 与持久化**：MySQL/Mongo 新增、读取、替换、确认删除及直接存储核对通过；两账号共享 lab，但旧 tasks/results 权限不变；最终替换 API/Worker 后，SQL/Mongo/Redis 教学内容和 Kafka 首次回执仍稳定可读。
- **Redis**：核对真实值与 PTTL、TTL 下降、实际到期缺失、覆盖重置及删除。故障时 lab 返回不可用，不把空值或旧任务缓存降级当成功；恢复后重新操作。
- **MongoDB**：独立 collection 写后回读、JSON 预算/键安全、故障错误与恢复通过，不用请求回显证明保存。
- **Kafka**：broker 生产确认与实际 consumer 回执分别核对；暂停 Worker 时已确认但尚未观察到，恢复后实际收到；重启后回执稳定。不可用发送保留不确定性，按原 ID 查询，不伪造 receipt 或自动重发。
- **浏览器**：四页无需 task 前置；增改删/取消、真实 Redis 到期、Kafka 收取、刷新/导航、桌面/手机及旧任务回归通过。超时/响应乱序/会话切换等精确竞态有补充测试，不扩大成所有真实网络故障保证。

真实 lab 探针日志阶段 `prepare`、`kafka-send-paused`、`kafka-received`、`mysql-unavailable`、`mysql-restored`、`redis-unavailable`、`kafka-unavailable`、`mongo-unavailable`、`restart-stable`、`cleanup` 均为 PASS。原 MySQL 五阶段探针也通过。四个 SIGKILL 窗口为 `after_outbox_publish`、`after_inbox_commit`、`after_claim`、`after_mongo_save`；`crash-windows.json` 记录 `status=passed`、`cleanup_verified=true`，四项均完成 prepared/boundary_verified/sigkill_verified/recovered。它们与迁移测试的 DDL 注入中断不是同一种实验。

## 3. 发现过的问题与修复，不隐藏失败

首个候选 `c3d65081` 的 [CI 39741761253](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39741761253) **不能作为全项通过证据**：Mongo 浏览器断言有 JSON 字符串转义错误；视觉复核另外发现旧样式与新双栏布局的 CSS 名称冲突。即使部分 API/测试成功，也不能忽略真实页面的布局问题。

修正提交 `ec1126d2`：

1. Mongo 文本断言按 `JSON.stringify` 的实际 JSON 表示比较，不把引号转义差异当数据写入失败，也不删除该断言逃避验证。
2. 新操作区改用命名空间类 `lab-workbench-grid`，避免旧组件说明样式污染双栏操作区；加入几何边界检查，覆盖桌面与手机的可见布局。
3. 对修正提交重新执行完整三个 CI job；38 项浏览器通过后，再对修正截图进行人工视觉复核，确认 Mongo/Kafka 操作区与数据区可用。不是用首轮旧截图或旧 run 代替重验。

实现阶段还修复并保留回归：不兼容额外 UNIQUE/约束与有效二进制排序规则检查；共享 producer 只依据本次回调确认；旧任务/DLQ topic 不得占用 lab 保留 topic；切页后 CSRF 刷新引发旧写请求重发的竞态。取消等待不会承诺撤销服务端已接受的写入。

既有 Starlette/httpx 弃用警告及 npm 环境选项提醒没有被隐藏；未为消除提醒擅自升级依赖、修改代理或运行 audit。

## 4. 命令与证据口径

下列入口已由本轮 CI 执行；具体参数、前置启动顺序与证据白名单以该提交的 [CI 工作流](https://github.com/kismetcccc/agent-stack-lab/blob/ec1126d27ee63bb401d29bb8705a11603a61e01c/.github/workflows/ci.yml)为准，不是请读者对用户日常栈直接运行故障脚本。

- 后端：`uv sync --frozen`、Ruff、`uv run pytest backend/tests tests/judge/test_capture.py -m 'not integration' --junitxml=artifacts/unit.xml`。
- 前端：`npm ci --no-audit`、`npm run typecheck`、`npm test`、`npm run build`。
- 真实升级：先仅启动隔离存储，再运行 `test_schema_upgrade.py` 的冻结 v1 升级及启动后旧身份/任务保留测试；之后才启动新 API/Worker。
- 真实主链路：`python scripts/test-http-smoke.py`、`bash scripts/test-integration.sh`、`bash scripts/test-crash-windows.sh`。
- 浏览器：UI overlay 就绪后，`TEST_BASE_URL=http://localhost:8081 bash scripts/test-e2e.sh`。

证据按层级读取：JUnit/XML 与实际 job 日志统计测试；升级/故障/重启 JSON 和日志核对业务事实；PNG 加几何检查核对可见布局。`judge-sanitized-evidence` 的 `judge-evidence.json` 对应精确 commit，30 cases、`capture_complete=true`、`quality_verdict=not_assessed_capture_only`、`provider_status=not_run`；只证明采集完整性，不是自然语言质量或 live 模型验收。

2026-10-22 08:09 UTC 已确认本轮三个 job 终态成功；以下四份下载 ZIP 的 SHA-256 与 GitHub artifact metadata 一致，metadata 的 workflow head 均为 `ec1126d27ee63bb401d29bb8705a11603a61e01c`：

| 归档 | Artifact ID | 已核对的 ZIP SHA-256 |
|---|---|---|
| `unit-evidence` | [`12411030067`](https://api.github.com/repos/kismetcccc/agent-stack-lab/actions/artifacts/12411030067/zip) | `3753faef46a1d3c45e4caf426dc95d5efbef6db87b7ccac18800238f39b98816` |
| `frontend-browser-evidence` | [`12410044973`](https://api.github.com/repos/kismetcccc/agent-stack-lab/actions/artifacts/12410044973/zip) | `97cf831940ac5d91c976a08c094776af7b522d2d9cc57a695d4cdff842007cde` |
| `compose-real-integration-evidence` | [`12410523464`](https://api.github.com/repos/kismetcccc/agent-stack-lab/actions/artifacts/12410523464/zip) | `4fa8b256e45ea04f084a2f1cfbd8c8c2ecd7e9f09017663e4af208de0b5a0b01` |
| `judge-sanitized-evidence` | [`12411071738`](https://api.github.com/repos/kismetcccc/agent-stack-lab/actions/artifacts/12411071738/zip) | `c9479494a88c8756f04c8bde87ddfb9043bf097a623a3256eff0aeb426994e22` |

浏览器归档共有 35 项，含 10 张组件截图：每个 `desktop-chromium` / `mobile-chromium` 项目各有 `component-home`、`mysql-real-record`、`redis-real-ttl`、`mongo-real-json`、`kafka-real-ack-and-receipt` PNG，位于 `test-results/browser-artifacts/component-playground-*/`；没有失败截图。8 个新增浏览器旅程均检查工作区宽度，手机编辑/结果区全宽纵向排列且不重叠，桌面双栏及结果区右边界符合预期。人工视觉复核覆盖修正后的桌面与手机 Mongo/Kafka 截图。

本轮 ZIP 路径/清单检查确认排除了 `.env`、storageState、outage/playground/crash 私密状态、traces 和 error-context 文件。凭据模式扫描只命中两处已对照源码确认的公开负向测试 URL 样例；没有其他 URI 密码、session cookie、Bearer 或私钥模式命中。**该有限扫描不是“所有可能秘密为零”的普遍证明**，公开范围仍限脱敏白名单。数据卷销毁只属于隔离 CI 的临时资源清理，绝不是用户本机更新步骤。

## 5. 本机升级与实际页面验收

2026-10-22 08:51 UTC，Windows + Docker 上的既有本机栈完成验收，`PLAY-07` 标记为**已验收**；连同云端 `PLAY-01..06`，本轮有限迭代已收口。

- **版本与迁移**：checkout 快进至同一精确代码提交 `ec1126d27ee63bb401d29bb8705a11603a61e01c`，工作区干净；显式 v1→v2 迁移成功，版本标记为 `[1,2]`。
- **配置与旧数据保留**：原 `.env`、`.env.compose.local` 字节未改且仍被 Git 忽略；原用户、会话、任务、事件、尝试记录及 Mongo 结果内部对照未变化，旧任务与 Agent 动作仍可读取。沿用原 project/数据卷，四个存储服务未重启；最终 7 个服务健康。
- **真实 Edge 操作**：MySQL CRUD、Mongo JSON CRUD 均通过，合成测试记录已清理；Redis 10 秒 TTL 的服务端 PTTL 实测由 `10000` 降至 `4363` 毫秒，再读取确认不存在；Kafka 生产确认与真实消费回执的 partition/offset 一致，合成消息历史按设计保留。
- **入口与范围**：Edge 已打开 `http://localhost:8081/#playground`。使用 deterministic，未发起付费模型调用，未改模型密钥；未使用删卷、换密码或重建空库完成升级。

公开报告仅记录结果，未上传本机原始截图或私密证据，不披露个人路径、账号、会话或旧数据内容。这次成功是已支持的 v1→v2 本机升级与功能验收，不延伸为通用回滚、备份恢复、HA、live 或 Kubernetes 验收。
