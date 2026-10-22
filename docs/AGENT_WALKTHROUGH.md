# 跟着一条任务，读懂单 Agent 如何使用后端

> **代码已通过本轮CI，真实LLM仍未验收。** 本文对应 `9c4a1908124b61eee4207dc5bb6cb172134fda06`；[本轮CI](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39721645077)通过140项后端单元/API测试、13项真实集成（11+2）、30项UI单元和24项浏览器测试。最终截图视觉验收与范围说明见 [单Agent验收报告](AGENT_TEST_REPORT.md)。没有实际调用真实模型；脚本测试和真实数据库测试不能替代真实LLM验收。

## 1. 先在界面提交这条任务

按 [UI_GUIDE.md](UI_GUIDE.md) 启动学习界面，创建本地教学帐号并登录。在“研究主题 / 任务要求”框中粘贴下文，点击 **“提交报告任务”**。当前界面在输入框占位文字和下方提示中提供脚本示例。

```text
目标：[search:销量] [stats]
材料：销量 10 20 30
```

这条任务适合观察，不是让你提供密码或模型密钥。完成后，选中任务，分别查看后台生命周期、执行尝试、Agent工具动作和最终结果。

预期统计结果如下；Decimal数值以字符串返回，count是整数：

```json
{"count":3,"sum":"60","min":"10","max":"30","mean":"20"}
```

最终答复还会包含明确的“deterministic 脚本测试控制器；无真实模型推理”标识与读到的文本。它不是一份真正由LLM研究生成的报告。

## 2. 基础设施与Agent执行的分工

```text
可靠交付线：API → MySQL任务+Outbox → Kafka → Inbox → Worker领取
                                                        ↓
单Agent执行线：读取文本 → 搜索“销量” → 观察命中 → 统计 → 最终答复
                                                        ↓
结果提交线：Mongo保存 → MySQL检查有效租约/fence并提交 → API授权读取
                                                        ↓
                                             Redis命中或Mongo读取 → 界面
```

中间那条执行线是**本示例的实际分支**，不是所有任务都必须经过的固定顺序。外面的可靠交付线负责“别丢任务、别让旧执行器覆盖结果”；里面的控制器负责“根据已有观察决定下一步”。

MySQL、Kafka、MongoDB、Redis是不同职责的组件，**不是四个Agent**。Worker是后台干活的程序，也不天然意味着智能决策。Kubernetes是后续部署概念，不是每条请求要再经过的一站，本轮没有引入它。

## 3. 从点击提交到开始执行：先看后端的可靠性

| 你观察到什么 | 实际发生什么 | 对照代码 |
|---|---|---|
| 点击提交，收到任务编号 | 路由验证会话、CSRF和幂等键；同一用户、同键、同请求返回原任务 | `backend/app.py` 的 `submit`；`backend/service.py` 的 `TaskService.create/same` |
| 任务进入pending | 同一个SQL事务创建Task与Outbox，尚未调用模型；HTTP 202只表示接单 | `TaskService.create/emit/audit`；表结构在 `backend/db.py` |
| 出现outbox_sent | relay把固定event_id交给Kafka，确认后才标记已发送；确认与落库之间崩溃可能重发 | `TaskService.relay_once`；`backend/adapters.py` 的 `KafkaBus.publish` |
| 任务进入ready | consumer先把事件记入MySQL Inbox并更新任务，再提交Kafka offset；重复event_id被去重 | `TaskService.receive`；`backend/worker.py` 的 `main` |
| 出现running和新的执行尝试 | executor领取任务，增加attempt_count/fence，设置租约，随后在SQL事务外执行 | `TaskService.claim/execute_once`；`backend/worker.py` 的 `executor` |

可以把fence理解为“这次执行的版本号”：旧执行器即使晚到，也不能用旧版本号提交新结果。`backend/domain.py` 集中规定允许的状态转换，Agent代码不另建一套任务状态。

## 4. 单控制器如何决定下一步

从 `backend/adapters.py` 的 `Model.run` 读起：它检查任务模式与Worker配置是否一致，然后选择一个控制器——deterministic使用 `ScriptedController`，live使用 `LiveController`——交给 `backend/agent.py` 的 `run_agent`。**一次任务不是两个控制器一起讨论。**

`run_agent` 不替控制器写固定业务流程，而是循环调用 `controller.next(prompt, observations, deadline)`。控制器只允许返回一个 `ToolCall` 或一个 `Final`。工具调用必须经过 `backend/agent_tools.py::execute_tool` 的允许列表、参数和大小检查；结果加入observations，再进入下一次决策。

本示例在 `ScriptedController.next` 中这样运行：

1. **还没有观察：** 返回 `read_text(offset=0,length=1000)`。工具只读取本任务prompt，返回文本、下一位置和截断标记。
2. **已经读过，发现 `[search:销量]` 标记：** 返回 `search_text`。搜索从“材料：”之后开始，所以不会把指令中的“销量”误当成材料命中。
3. **搜索结果确实有命中，而且有 `[stats]` 与“材料：”：** 返回 `numeric_stats`，范围是“材料：”后到输入结尾。它统计的是整个材料范围，不只是命中词附近的数字。
4. **已有统计观察：** 返回 `Final`，将文本片段与统计结果组成明确标注的测试答复。

这次用了4次决策、3次工具调用。成功结果中会有7条记录：每个工具各有一条tool_call和tool_result，最后一条final。

### 做一个很小的对照实验

把目标改成 `[search:利润] [stats]`，材料仍为“销量 10 20 30”，提交为新任务。

搜索“利润”没有命中，脚本便**跳过统计，直接final**。这证明下一步确实依赖工具观察，而非无条件执行三个工具。但分支规则与markers仍是程序员写好的脚本，**不是LLM理解了销量或利润**。当前脚本也不是自动读完所有分页的通用研究助手：read_text首次只请求1000字符，截断标记应如实理解。

真实live控制器位于 `backend/agent_provider.py::LiveController.next`：它把目标、允许工具和此前观察发给已配置provider，由模型选择工具或结束。`normalize` 将响应变成受限的ToolCall/Final；不接受多工具调用或截断结果，不保存reasoning字段，也不把工具调用附带的辅助文字当作隐藏推理记录。

## 5. 算出60之后，还不能立即宣称任务成功

`run_agent` 返回的文档先回到 `TaskService.execute_once`：

1. 用task_id与attempt_id组成稳定result_id。
2. `MongoDocuments.save` 保存这一attempt的不可变结果，包括公开动作steps。
3. `TaskService.finalize` 再检查SQL中的任务仍为running、fence仍匹配、租约仍有效，才提交succeeded和result_id。

因此Mongo中有一份文档，并不等于任务已经成功。保存后、SQL提交前崩溃，可能留下孤儿文档；API不能把它当成正式成果。

查询则走反方向：`backend/app.py` 的results/agent_steps路由调用 `TaskService.document`，**先SQL验证任务所有权和已提交结果引用**，再经 `ProgressCache.read_result` 查询Redis。未命中才读Mongo，并尝试缓存。Redis不可用可降级；它不裁决任务成功。结果中的cache_status只表示这一次读取，不是Redis永久在线证明。

界面对应代码：`frontend/src/App.tsx` 负责提交与任务展示，`frontend/src/AgentActions.tsx` 读取 `/agent-steps` 并展示动作。

## 6. 两种记录不能混为一谈

| 界面/接口 | 数据来自哪里 | 能说明什么 |
|---|---|---|
| 后台生命周期 `/events` | MySQL的TaskEvent | pending、ready、running、成功/失败等后台转换；不是模型思维 |
| 执行尝试 `/attempts` | MySQL的Attempt | 重试次数、fence、开始结束和outcome |
| Agent工具动作 `/agent-steps` | 已提交成功结果中的Mongo steps，可经Redis缓存 | 工具名、参数、返回结果及final；不是实时动作流 |

运行中或失败任务返回not_committed和空动作列表，**不能据此断言没有调用过工具**。本MVP没有完整失败/崩溃前工具审计。旧版echo或单次模型结果标为legacy，不会被包装成新Agent动作。

## 7. 安全范围和预算，先知道这些就够了

- 工具唯一材料是当前任务prompt，即task_input。没有其他任务读取、文件、URL访问、shell或写操作。粘贴URL只是输入一段文字，不会抓取网页。
- read/search按实际JSON UTF-8字节预算截断，next_offset指向可继续的位置。字符数合规不代表字节数一定合规。
- numeric_stats是**词法数字统计，不是财务解析**。`10 20 30`和`10、20、30`可用；`1e6`、`1,000`、货币格式或表达式会被拒绝，不能把1e6偷偷拆成1和6。最多200个数字，每个≤32字符且绝对值≤10^12。
- 每attempt最多6次决策、5次工具调用；执行至多60秒，还要受实际租约剩余时间减15秒持久化余量约束。单工具结果≤4KiB，累计≤16KiB，最终答复≤8KiB；超限是失败，不是假装完成。
- live传输有可取消总deadline与64KiB请求/响应上限；适配器不内嵌重试。暂时故障由现有任务attempt机制处理。
- 最多请求次数是 **6×实际attempt上限**，默认3次attempt才是18。模型响应丢失、Worker崩溃或持久化失败可能重放并重复付费，不能承诺只调用/计费一次。

live仍需用户后续在受保护环境中配置并授权，且单独验收provider兼容性与费用；**不要把key发到聊天、前端表单或公共仓库**。当前没有真实provider调用。启用live也意味着目标和材料将发往所配置的provider，不宜用敏感资料试跑。

## 8. 遇到异常，先定位哪一层

| 现象 | 先看哪里 | 不要误判成什么 |
|---|---|---|
| 一直pending | Kafka可用性、Outbox relay | 不是Agent“正在思考” |
| running后重试、attempt增加 | Worker中断、租约恢复；看attempts与脱敏错误 | 不是必然模型质量差 |
| agent_tool_rejected | 参数/数字格式/允许列表，见agent_tools.py | 不是数据库损坏 |
| agent_budget_exceeded | 决策/工具/字节/时间限制，见run_agent | 不应无限加重试来掩盖 |
| Mongo写失败 | 结果存储；任务不能提交成功 | Redis不能替它证明成功 |
| Redis unavailable但仍拿到结果 | 缓存降级读取Mongo | 不代表结果丢失 |
| document_unavailable | 已授权结果文档暂不可读 | 不能显示成“没有工具动作” |
| 他人任务返回404 | TaskService.owned资源授权 | 知道task_id也不能绕过 |

先用本例把“接单→交付→决策→工具→提交→读取”串起来，再配合 [FAILURE_LABS.md](FAILURE_LABS.md) 做隔离环境故障实验。你学到的重点不是组件数量，而是每一层负责什么、哪里可能失败、失败后谁有资格决定结果。
