# 开发与验收记录

本记录对应[开发任务清单](DEVELOPMENT_PLAN.md)，只记录已经发生的检查，不用计划或代码文件代替运行证据。

## 当前结论：学习型 v1 已验收（2026-10-22）

19 项必需任务已完成；正式项目许可证等待所有者确认，可选真实模型全栈仍未验收。当前被测、已发布源码为 `102491d29238c6349311f24643511041ed2af7f2`，对应 [CI 39731470818](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39731470818)，checks / compose-integration / frontend-browser 三个 job 全部成功。此后的收口提交只更新 Markdown，不把文档提交伪称重新执行过代码测试。

| 验收项 | 实际结果 | 证据位置 |
|---|---|---|
| 后端/API/采集器离线回归 | 409 通过 | unit-evidence / unit.xml |
| 真实四存储 pytest 集成 | 13 通过：11 正常/契约/Agent + 2 恢复 | compose-real-integration-evidence / integration.xml、recovery.xml |
| 真实 MySQL 停库与恢复 | 1 个脚本场景，5/5 阶段 | mysql-outage.xml 与步骤日志 |
| 精确 SIGKILL | 发布确认后、Inbox 提交后、claim 后、Mongo 保存后，4/4 场景通过 | crash-windows.xml/json；每个场景都有边界、kill 后持久状态和恢复检查 |
| 清理与健康 | 无 hook 的 Worker 恢复通过；六个常驻服务健康；最终 CI 专用卷清理成功 | cleanup_verified=true、services.txt 与 CI 日志 |
| 可执行 HTTP 示例 | 注册/登录、CSRF、幂等、异步查询、结果/工具步骤、退出后 401 通过 | Execute documented standard-library HTTP main-function smoke 步骤 |
| 私密构建上下文保护 | 两个 Docker job 都实际验证 55 个私有合成路径被排除、11 个公开源路径保留 | Verify private files are excluded from Docker build contexts 步骤 |
| 前端 | 30 单元 + 30 桌面/手机浏览器通过；类型检查与构建通过 | frontend-browser 日志及 browser.xml |
| 冻结 Judge 采集 | 30 条完整；质量未评分、provider 未运行 | judge-sanitized-evidence；不增加精细 AI 评测门槛 |

全部 JUnit 的 failures / errors / skipped 为 0。四个宕机场景与 MySQL 场景不是额外 pytest 用例，HTTP/构建检查按脚本步骤单独报告，不把不同层级数字简单混加。

四份下载归档的 SHA-256 已与 GitHub 对应；检查未发现私密状态文件或所检查的敏感模式。这是限定范围核对，不是全历史绝对无秘密证明。实际用户配置没有上传或修改，默认 CI 无真实模型凭据。

| GitHub 归档 | SHA-256 |
|---|---|
| unit-evidence | `aa1e3999609b2825d620877a197e17f50a670ce3f16a8b77ef0baf2e31a57cb2` |
| frontend-browser-evidence | `e101012406a355615910b779ee2c145241105c8847f3f204d45736c1ccd2078c` |
| compose-real-integration-evidence | `0511496fb3d1c0339765d1728015e28735eb55c9bb07b87cc95e2974feadf895` |
| judge-sanitized-evidence | `60c29105fd2d1aeeafa9665a36ca71475b43864d5e8bb5a1296d17fc7090f520` |

文档检查：32 篇 Markdown 的相对文件/标题链接通过；运维文档 24 个 Bash 代码块只做语法检查。备份恢复步骤、手工 curl 逐行执行、Kubernetes、生产加固和完整 live Agent 不在已实跑声明中。项目 LICENSE 仍未添加；上游资料使用外链与原创摘要，不整篇搬运。完整传递依赖许可兼容性及漏洞审计未宣称完成。

后面的迭代记录保留当时基线，供追溯，不将历史的“待验证”误读为当前终态。

## 迭代 1：后端功能审计与学习文档（2026-10-22）

- 计划先发布：`d4417229db468286682538ba02597ec33951c253`。
- 被核对的运行时/测试基线：`f36523fa82c3621ac0dd0f36285e7f57e3532245`。
- 真实 CI：[39725461902](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39725461902)，所有必需 job 成功。
- 本轮文档提交不修改运行时代码，不将文档检查描述为重新运行 Docker。

### 已核对的证据

| 检查 | 结果与边界 |
|---|---|
| 后端与采集器 | 145 项通过；云端源码审计时重跑同组测试和 Ruff 通过 |
| 真实 MySQL/Kafka/MongoDB/Redis 集成 | 11 项常规/API/Agent + 2 项恢复，共 13 项通过 |
| 真实故障探针 | 既有 Redis、Kafka、Mongo 停机与 Worker 重建在 CI 成功；这些脚本阶段不全计入 13 个 pytest 用例 |
| 前端 | 30 项单元、30 项真实桌面/手机浏览器测试通过，独立于后端 job |
| 已有 Judge 证据 | 28 个真实 API 输入和 2 个隔离运行时探针已采集；采集完成不表示全部用户目标完成。按当前范围不继续扩展细粒度评分 |
| 独立 provider 检查 | 一次极小合成请求返回正常；仅证明端点/鉴权/基本响应，不证明工具选择、完整 live 链路或一般模型质量。没有将凭据放进仓库或 CI |
| Kubernetes | 未运行真实集群；当前 CI 没有 Kind job |

四份 CI 归档的校验摘要已与 GitHub 返回值对应。公开文档只引用脱敏结果，不提交原始认证状态、Cookie、CSRF token、数据库连接信息或私密模型配置。

### 文档交付

- [模块功能契约](MODULE_CONTRACTS.md)：API/Auth、MySQL、Kafka、Worker、MongoDB、Redis 的职责、输入输出、权威、失败交接、代码入口与功能—测试映射。
- [资料索引](OPEN_SOURCE_RESOURCES.md)：11 组官方/开源项目资料、版本与许可边界、原创导读和小练习；不是第三方文档镜像。
- [文档导航](README.md)：按调用链和学习任务组织入口。
- README、Agent.md、API 契约及基础设施说明校正了当前/历史证据、可选 UI 范围、独立 live 连通性与完整 live 验收的区别。
- SQL/EXPLAIN 示例是只读学习材料，已核对表/索引名称，**没有声称已执行性能或容量测量**。

### 确认缺口与下一轮

| 编号 / 任务 | 审计发现 | 当前处理 |
|---|---|---|
| BUG-001 / FIX-ENV | 初始化脚本拒绝任何已有 `.env`，无法为先填写模型配置的流程安全补齐空白数据库凭据 | 实现显式补缺模式及隔离测试；不删除或覆盖已有密钥，不在用户电脑自动生成凭据 |
| BUG-002 / TEST-02 | 可选故障 overlay 的 3 秒租约小于 Agent 15 秒持久化余量，到不了正常 Mongo 保存暂停点 | 待修复测试配置并验证；标准恢复测试不是此精确窗口的真实运行证据 |
| BUG-003 / TEST-02 | 可选暂停钩子没有使用传入的目标 task ID | 待补目标过滤和回归；不开放 HTTP 故障开关 |
| TEST-01 | 既有真实故障测试未明确停 MySQL 验证缓存不能绕过 SQL 授权 | 正在增加隔离 CI 探针，真实运行结果尚待新提交 CI |
| 可观测性边界 | Worker 心跳仅覆盖 consumer poll；HTTP 指标不等于完整业务指标/分布式 tracing | 当前准确记入模块与运维文档，不伪称覆盖全部组件健康 |

本轮未发现额外的数据权威、资源所有权或正式结果提交的主链路阻断缺陷；这是限定源码与测试范围内的审计结论，不是全面安全认证或“无 bug”保证。

## 下一轮验收要求

新增代码先做针对性回归，再跑所需完整 CI，成功后在这里记录实际提交与新测试数量。任何故障实验必须区分单元/状态构造、真实组件测试和精确进程宕机；失败不得改名为未运行来隐藏，也不得用旧绿色提交代替新结果。

正式开源许可仍由仓库所有者选择；公开仓库和本报告都不替代许可证授权。公网部署、Kubernetes、真实模型全栈和灾备能力继续按任务清单的独立边界处理。

## 迭代 2A：初始化与 MySQL 故障探针（已验收）

- FIX-ENV 新增显式安全补缺模式；58 项隔离初始化测试通过，真实用户配置未读取或修改。原生 Windows 已有文件补齐明确拒绝，不冒充已完成跨平台验收。
- TEST-01 新增 MySQL 停机/恢复五阶段探针及 25 项离线辅助测试；这些 MockTransport/命令替身单元用例不是停库证据。
- 当前共享源码的后端/采集器合计 228 项测试由协调检查重跑通过，Ruff 和 Bash 语法检查通过；有一条现有 Starlette/httpx 弃用警告，未因此更换依赖。
- 真实 MySQL 探针将独立生成 `mysql-outage.xml`，计一个五阶段脚本场景，不把它说成新增五个 pytest 集成用例。原有 13 项集成与其他故障路径保留。
- 发布提交 `9f892c6742fa683f8f46edac7b46e769587c3a78` 的 [CI 39728628773](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39728628773) 已全部成功：228 项单元/采集器、13 项真实 pytest 集成、独立 MySQL 五阶段场景 1 项，以及 30 项前端单元与 30 项浏览器测试通过。
- 已核对归档摘要、五阶段 XML、实际停库日志与健康恢复记录；原 Redis/Kafka/Mongo/Worker 故障仍通过。脚本先恢复数据服务再恢复 Worker，保留卷；仅 CI 最后的专用清理删除了该次 runner 的临时卷。


## 迭代 2B：精确恢复、HTTP 示例与交付保护（已验收）

本轮没有扩大 Agent 的工具权限或增加基础设施；代码改动集中在测试开关、可执行示例和构建上下文保护。默认执行仍为 deterministic。

| 项目 | 已完成的实现 / 离线证据 | 真实验收边界 |
|---|---|---|
| TEST-02 | 30 秒故障租约；task/run 双重过滤和私有 marker；发布、Inbox、claim、Mongo 四窗口；SIGKILL 前后持久状态核对、退出码 137、真实 lease 回收、恢复无 hook；66 项离线回归 | 新 CI 运行四个脚本场景，生成 crash-windows.xml/json；不计作新增四个 pytest 用例，四场景实跑通过，cleanup_verified=true |
| TEST-03 / DOC-01 | 标准库 HTTP 脚本：readyz 模式门禁→注册/退出/登录→CSRF 轮换→幂等提交→任务结果/事件/尝试/工具步骤→退出/401；83 项离线回归 | 新 CI 独立运行 scripts/test-http-smoke.py 并通过；不是用离线替身充当真实 HTTP 闭环 |
| BUG-004 / FIX-01 | 原 .dockerignore 未完整隔离根/嵌套秘密目录和数据库文件；补过滤及 55 个私有、11 个公开的纯合成路径夹具；32 项离线回归 | 每个 Docker 应用构建前先做真实 FROM scratch/COPY/export 检查，失败则不继续真实上下文构建；两个 Docker job 均实跑通过，不声称发生过实际泄漏 |
| 文档与开源准备 | 运维、贡献、安全、第三方来源和发布检查清单已补齐；32 篇 Markdown 的相对文件/标题链接检查通过 | 备份恢复步骤未实跑；完整依赖许可兼容性和漏洞审计未通过认证；项目许可证仍待所有者批准 |

本地合并检查：409 项后端/证据采集器测试通过，Ruff 通过，两个故障 Bash 脚本语法通过，13 项真实集成测试可收集。现有 Starlette/httpx 弃用警告仍保留。这里的“本地”指云端代码工作区，不是用户电脑。

补充的关键断言：发布后暂停只阻塞 relay，任务可由其他循环推进甚至成功，所以按相同 event ID 的真实重复投递及 Inbox 去重验收，不错误要求任务仍 pending。最终结果的 attempt ID 从 SQL/Mongo/工具步骤核对，不杜撰 ResultResponse 中不存在的字段。旧 hook-evidence 分支已移除，避免与新 crash_probe.py 出现双份判断逻辑。

crash-state.json 是临时私密认证状态，清理时删除，且明确排除出归档；只发布脱敏的四场景 XML/JSON。Docker 合成上下文不复制真实项目或读取任何 .env/.secrets，容器不启动，按本次唯一名称与归属标签清理。
