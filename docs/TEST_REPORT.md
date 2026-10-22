# 后端首轮验收报告

## 被测对象与结论

- 被测 commit：`cc17a052a2c3ad5cd36d79a5d1500704185c7fe2`
- 被测 tree：`6326cec6fb47b254a55ec62d556041ae977f34f0`
- GitHub Actions run：[`39715365618`](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39715365618)，attempt 1，`push` 触发。
- 开始：2026-10-22 03:10:15 UTC；最终状态更新时间：03:14:16 UTC。
- 结论：两个 job 均为 `completed / success`。真实容器构建、启动、迁移及本报告列出的后端测试通过。

**范围限定：模型使用明确的 deterministic 测试替身，不是实际大模型调用；MySQL、Kafka、MongoDB、Redis 使用真实容器服务，不是 mock。**
单元测试与真实集成分别统计，不能把 20 个单元测试计为真实基础设施集成。
本报告是上述 commit 的证据；后续仅添加本报告的文档提交没有改变被测代码，但不能把新 commit 冒充已执行此次测试的 commit。

## Job 与测试结果

| Job | 证据 | 结果 |
|---|---|---|
| `checks` | [job 119616065026](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39715365618/job/119616065026) | 冻结依赖安装、后端 lint、离线 Compose/YAML 结构检查通过；20 个单元测试通过，日志用时 5.13 秒 |
| `compose-integration` | [job 119616155651](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39715365618/job/119616155651) | 应用镜像真实构建、Compose `--wait` 启动、7 个链路/API 测试及 2 个恢复测试、实际停机实验、证据上传与 CI 资源清理均通过 |

下载后的 JUnit XML 已检查：链路/API **7 tests / 0 failures / 0 errors / 0 skipped**；恢复 **2 tests / 0 failures / 0 errors / 0 skipped**。

### 7 个真实链路/API 测试

1. 完整任务链路与重复 Kafka 事件。
2. 并发幂等请求与同键不同内容冲突。
3. 认证、CSRF、任务所有权与安全 DTO。
4. 会话轮换/过期、输入验证与分页。
5. 幂等键按字节区分，不被 MySQL 默认排序规则误合并。
6. 统一校验错误与分块请求体大小限制。
7. 认证写接口的 Origin 与 CSRF 边界。

### 2 个恢复测试

- `test_replay_ack_gap_and_expired_lease_fencing`：构造重放/确认间隙及租约过期状态，验证恢复和旧 fencing token 拒绝。
- `test_bounded_retry_emits_durable_dlq`：有限重试与持久化 DLQ。

这些使用真实数据库/消息服务，但**构造恢复状态不等于已在精确指令窗口真实杀死进程**。不得称为所有 crash window 的真实进程宕机验收。

## 实际停机实验

以下不是单纯 mock 异常：脚本实际停止/启动对应 Compose 服务，或替换 Worker 容器，job 日志记录了操作和断言。

| 实验 | 日志观察与断言 |
|---|---|
| Redis 停止 | 接受任务；Redis 停止期间任务最终成功，SQL 已提交结果引用且 Mongo 结果可读；随后恢复 Redis |
| Kafka 停止 | 任务被接受后保持 SQL pending，没有虚假成功；Kafka 重启后任务完成，验证待发布工作可恢复 |
| MongoDB 读取故障 | 对已有成功任务停止 Mongo：结果读取返回 503；SQL 已提交状态仍为事实来源；存活检查不受影响，关键依赖就绪检查失败；恢复 Mongo 后结果再次可读 |
| MongoDB 写入故障 | 停止 Mongo 后提交任务，断言不出现虚假成功；恢复 Mongo 后任务成功且结果可读 |
| Worker 替换 | 先停 Worker，再提交任务，观察 pending；通过 `--force-recreate` 替换 Worker；恢复后任务成功，SQL 结果引用和 Mongo 文档均可读 |
| 日志模式检查 | API/Worker 日志中未发现测试所检查的凭据、令牌、连接字符串模式；这不是“绝无秘密泄漏”的一般性证明 |

Worker 替换实验的时点是停止后入队，并非在模型调用、Mongo 写入后 SQL 提交前、Outbox 发送确认后或 Inbox 提交后等精确窗口执行 SIGKILL。

## 服务、镜像与运行观察

实际上传的 `services.txt` 记录如下镜像标签与容器状态；它们是**已运行容器的镜像标识**，不是通过数据库 `SELECT VERSION()` 等命令独立获取的运行时版本输出。

| 服务 | 已运行容器镜像标识 | 证据快照 |
|---|---|---|
| MySQL | `mysql:8.4.7` | healthy |
| Kafka | `apache/kafka:4.0.0` | healthy |
| MongoDB | `mongo:8.0.6` | healthy |
| Redis | `redis:7.4.2` | healthy |
| API | `agent-stack-lab-api:local` | healthy；仅 `127.0.0.1:8080 -> 8000/tcp` |
| migrate | `agent-stack-lab-api:local` | Exited (0) |
| Worker | `agent-stack-lab-api:local` | health: starting，见下述快照说明 |

构建日志实际解析并构建 Python 基础镜像：
`python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db`。
`uv==0.13.4` 安装成功。单元 job 的 Python 输出为 3.12.15；容器集成 pytest 输出为 Python 3.12，不能混作同一解释器的补丁版本。

**Worker 快照说明：**故障测试已在替换 Worker 后等待并验证任务恢复成功（03:14:08 UTC 左右）。退出清理随后再次重建 Worker，紧接着采集 `services.txt`，所以该快照显示新 Worker 刚启动、健康检查尚未收敛。此前业务恢复成功和最后快照尚处于 `starting` 是两个不同时间点；本报告不声称最后快照全部 healthy。

## 可复核证据

- [单元测试 artifact：unit-evidence](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39715365618/artifacts/12398523692)
  - ID：`12398523692`
  - ZIP SHA256：`4987b2f889666beb13ae12ea947711044505ef63d01966d4a553f629378510ab`
- [真实集成 artifact：compose-real-integration-evidence](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39715365618/artifacts/12399215271)
  - ID：`12399215271`
  - ZIP SHA256：`af237a763cf67a46db3b39325f17e8dd613ebc534be2f692b14d96eb0fa3673a`
  - 已实际下载，SHA256 与 GitHub artifact 元数据一致；ZIP 恰含四个文件：
    - `artifacts/compose/services.log`
    - `artifacts/compose/services.txt`
    - `test-results/integration.xml`
    - `test-results/recovery.xml`
  - ZIP 文件清单中没有 `.env`、`.secrets` 或 `outage-state.json`。这项检查仅确认该归档内容，不等于对整个环境的安全审计。

GitHub 当前给出的 artifact 到期时间为 2027-01-20 03:10:15 UTC；链接受仓库权限和 artifact 保留策略影响。

## 非阻塞警告与未验收项

观察到但未导致失败的警告：集成 pytest 未采用项目根配置导致 `integration` 标记警告；非 root 测试容器无法写入 `/tests` 的 pytest 缓存；单元测试客户端及部分 Actions 的 Node 运行时弃用警告。它们不是被跳过的测试，亦不能静默描述成“零警告”。

下列内容**未在本轮验收**：

- 真实模型 API、供应商超时/限额/计费及响应丢失后的重复计费行为。
- 在 Outbox 确认与标记、Inbox 提交与 offset 提交、Mongo 写入与 SQL 成功提交等精确窗口真实 SIGKILL 进程。
- 执行中的模型调用被杀死、长时间网络分区、MySQL 故障与备份恢复。
- 浏览器/UI、前端构建、网关及用户电脑环境。
- Kubernetes/Kind、NetworkPolicy 执行、对象存储、搜索、可观测性外围组件。
- 多 Worker/多 relay 并发、生产高可用、生产安全评审或公网部署。
- 压力/负载、吞吐/延迟、CPU/内存/磁盘占用、稳定运行时长、可靠的最低硬件配置。

编写环境没有 Docker，未将其本地静态检查冒充容器运行；本报告真实服务证据来自上述 GitHub Actions runner。CI job 耗时包含构建、拉取与测试，不能用作稳定态资源占用或性能承诺。
