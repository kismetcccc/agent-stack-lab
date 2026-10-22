# 贡献指南：先证明后端行为，再完善学习说明

欢迎修正文档、补充可复现测试和修复实际缺陷。请先读 [Agent.md](Agent.md)、[开发任务清单](docs/DEVELOPMENT_PLAN.md) 和 [API 契约](docs/API_CONTRACT.md)。当前目标是中文后端学习型 v1，不是生产平台；不要为了增加组件数量重写已经满足契约的实现。

**许可尚待仓库所有者选择。** 公开仓库不等于已采用 MIT 或其他开源许可证；本指南不构成新的许可授予、版权转让或 CLA。准备提交第三方代码前，先说明来源与授权；正式合入贡献所需的许可安排应由维护者确认。参考 [第三方清单](docs/THIRD_PARTY_NOTICES.md)。漏洞和秘密泄漏请按 [安全说明](SECURITY.md) 私下报告，不发公开复现详情。

## 1. 开发前提与可复现依赖

| 工作 | 前提 | 锁定入口 |
|---|---|---|
| 后端静态/单元检查 | Python 3.12；当前 CI 使用 `uv==0.13.4` | `pyproject.toml` + `uv.lock`，使用 `uv sync --frozen` |
| 前端开发与检查 | 当前 CI 使用 Node.js `24.22.1`，npm | `frontend/package.json` + `frontend/package-lock.json`，使用 `npm ci --no-audit` |
| 真实组件链路 | 可用 Docker daemon、Compose v2、Bash；能拉取固定版本镜像 | `compose.yaml`、Dockerfile；镜像固定 tag 尚不是不可变 digest |
| 浏览器测试 | 真实后端及 UI 网关；Playwright Chromium 和所需系统库 | `tests/e2e/package-lock.json`；脚本首次运行会下载浏览器 |
| 基础设施结构检查 | Python；CI 另安装 `PyYAML==6.0.3` | `scripts/infra-validate.py` 和 CI 工作流 |

Linux 是当前真实 CI 环境。Windows 建议使用 WSL2 的私有 Linux 文件系统；不宣称原生 Windows 初始化或 Docker 行为已经验收。不需要真实模型账号或 API key；不要将自己的本地模型配置复制到 CI。

安装上述工具后，在仓库根目录建立后端环境：

```bash
uv sync --frozen
# 只在需要前端时执行；不自动提交依赖图给 npm audit 服务
(cd frontend && npm ci --no-audit)
```

不要为解决安装失败直接删除锁文件或升级全部依赖。依赖升级应单独说明原因、精确版本差异、上游变更、许可变化和回归结果，同时提交 manifest 与 lock。固定版本不是“没有已知漏洞”的声明。外部依赖扫描可能发送依赖信息，启用前需单独确认数据范围与授权；本流程没有要求运行 `npm audit`。

## 2. 初始化与启动：默认无模型凭据

先确认这是你有权操作的独立开发目录和数据栈，而不是保存真实资料的服务。初始化会写本地私有 `.env`，不打印凭据；不要打开或上传该文件给别人排障。

```bash
# 尚无 .env 时，创建随机开发数据库凭据
python scripts/infra-init-env.py
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 300
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8080/readyz
```

已有 `.env` 时，默认初始化拒绝覆盖。不要删除旧文件、把密码换成示例值，或以删卷解决初始化提示。本轮 `FIX-ENV` 新增显式 `--fill-missing`：只补必需开发凭据中的缺失/明确空值，保留已有非空值；不承担密码轮换。**仅在这些缺失凭据尚未用于初始化服务时适用；已有数据卷而密码丢失时，先找回原值或制定数据库侧轮换方案，不随机补值。** 支持格式、平台边界、拒绝条件见 [配置说明](docs/CONFIGURATION.md)，验收以对应新提交测试为准，不由旧基线 CI 推断。遇到含糊配置、重复键、符号链接或并发修改，应先停止并查明原因。

默认 `MODEL_MODE=deterministic`，结果中的 `controller_mode=scripted_test` 表示脚本测试控制器。`LAB_MODE=production` 只表示使用真实组件适配器，不代表生产安全；默认 Compose 不透传 live 所需变量，单独把 key 写进 `.env` 不会启用 live。注册、CSRF、幂等提交和结果查询见 [故障实验中的 HTTP 流程](docs/FAILURE_LABS.md)；可选 UI 见 [UI 指南](docs/UI_GUIDE.md)。

```bash
# 普通停止：保留命名数据卷
docker compose down
# 若启动时使用 UI 覆盖文件，停止时也使用同一组文件
docker compose -f compose.yaml -f compose.ui.yaml down
```

**不要在含有需保留数据的环境运行 `down -v` / `down --volumes`。** 修改 `.env` 不会更新已初始化数据库里的密码。仅 `config --quiet` 成功不能证明镜像已拉取或服务已运行；Docker 不可用时，明确报告“真实集成未运行”，继续可执行的静态与单元检查。

## 3. 分层验证，不用 mock 冒充集成

### 最小后端检查

```bash
uv run --frozen ruff check backend tests/judge
uv run --frozen pytest backend/tests tests/judge/test_capture.py -m 'not integration'
```

测试用替身与合成数据，不读取真实 `.env`，不调用收费模型。变更初始化脚本时，补充临时目录测试；不得用真实凭据文件试验覆盖/拒绝分支。脚本/清单改动还需运行适用的 `bash -n`、Python 语法/单元和结构验证，不能仅依赖上面的 Ruff 路径。

### 真实集成与故障恢复

仅在 **已启动、可中断、只有合成数据** 的四组件栈执行：

```bash
bash scripts/test-integration.sh
```

该脚本会停止/恢复依赖或 Worker，不适合共享服务。检查退出状态、服务恢复状态及 `test-results/*.xml`，不能只截取最后一行。MySQL 停机新增覆盖、精确 SIGKILL 实验等本轮修改必须有新证据；[TEST_PLAN](docs/TEST_PLAN.md) 和 [FAILURE_LABS](docs/FAILURE_LABS.md) 区分标准测试、边界注入与可选精确宕机实验。不要将 `scripts/test-crash-windows.sh` 当成已经通过的默认 CI 步骤。

### 前端及浏览器（涉及 UI 或共享契约时）

```bash
(cd frontend && npm run typecheck && npm test && npm run build)
docker compose -f compose.yaml -f compose.ui.yaml up -d --build --wait --wait-timeout 300
bash scripts/test-e2e.sh
```

浏览器脚本会安装锁定 npm 依赖及 Chromium；CI 还安装浏览器系统依赖。缺少网络/浏览器库时写明阻塞，不用静态截图替代真实浏览器测试。只上传经检查的合成数据截图与允许的报告，不上传会话、完整 trace、Cookie 或整个测试目录。

### 完整 CI 与证据格式

[CI 工作流](.github/workflows/ci.yml) 是实际命令来源：`checks`、`compose-integration`、`frontend-browser` 分别验证静态/单元、真实存储、可选界面。完整发布验收须检查 **本次远端 commit** 的所有必需 job；Judge 采集验证证据完整性，不等于语义质量评分，也不要求增加 live 案例。

每次报告记录：`commit / 环境 / 命令 / 真实依赖或替身 / 通过、失败、未运行或阻塞 / 数量 / 脱敏证据位置`。现有 `f36523fa` 的 [CI 39725461902](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39725461902) 是 145 项后端/采集器、13 项真实集成、30 项 UI 单元、30 项浏览器的历史绿色基线，**不是本轮新增代码已通过的证明**。

## 4. 实现、接口、文档一起改

- 先写失败复现，再做最小修复；说明正常行为及故障行为。保持 MySQL 状态权威、事务 Outbox/Inbox、租约/fencing 和先授权后查缓存。
- API 改动同步 [API_CONTRACT](docs/API_CONTRACT.md)、OpenAPI/schema、curl 示例、前端类型/调用及正反例测试；不能只改某一份字段表。
- 模块改动同步 [模块契约](docs/MODULE_CONTRACTS.md) 的职责、函数调用链、持久化、失败恢复、权限、测试和限制。
- 新工具仍须最小权限、有界输入/输出/次数/时间。不得暗中加入 shell、任意文件/网络访问或真实副作用。
- 新文档写清前提、操作、预期观察与未验收部分；引用官方原始来源，写自己的解释，不复制整篇文档或无授权代码。
- 不使用“端到端 exactly-once”“生产安全”“真实模型已全栈验收”等没有证据的结论。Kubernetes、HA、多 Worker 和新外围组件不是本轮的默认任务。

## 5. Issue / PR 提交清单

普通问题请给出最小合成输入、版本、复现命令、预期与实际行为。敏感问题走 [SECURITY.md](SECURITY.md)。PR 建议小而单一，并列明对应计划 ID：

- [ ] 解释问题、改动范围、为什么没有更小方案，以及数据/兼容性影响。
- [ ] 接口、实现、测试、示例、模块文档和任务状态一致；没有误改其他人的工作。
- [ ] 给出实际执行结果及未运行原因，区分本次检查与历史基线。
- [ ] 依赖变更包含锁文件和第三方许可清单更新；没有擅自修改项目许可证。
- [ ] 检查本次差异与待提交文件，没有 `.env`、真实 key、私人 endpoint、用户输入、数据库、Cookie、日志或未脱敏截图。
- [ ] 普通命令不删卷，不改用户电脑配置，不启用 live 或增加收费 CI/云服务。
- [ ] 相对链接有效；非生产限制与剩余风险已在 [发布清单](docs/RELEASE_CHECKLIST.md) 对齐。

提交 PR、合并、创建 release/tag、部署公网是不同动作。只在相应授权范围内操作；发布后核对远端 commit 和其 CI，不把本地文件存在描述为发布完成。
