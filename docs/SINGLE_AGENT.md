# 受限单 Agent：最小实施契约

状态：**实现中；尚未验收**。日期：2026-10-22。

本契约先于实现提交。UI基线 `382da456` 已通过 [CI 39720266829](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39720266829)，包含真实服务、17项UI单元和18项浏览器测试，桌面与手机截图已复核；实施门槛已满足。此前失败、修复与范围见 [UI验收报告](UI_TEST_REPORT.md)。本轮没有实际provider调用、凭据配置或用户电脑操作；下面的Agent能力仍需独立代码和测试验收。

## 1. 为什么还需要这一层

扩展前的UI基线中，`Model.run` 在 deterministic 模式回显文本，在 live 模式最多进行一次 Chat Completions 请求；它没有工具选择、观察和再次决策。现有可靠后台已经解决排队、事务、重试和恢复，不能因为组件齐全就称它为自主 Agent。

```text
基础设施层（已存在；不改变权威边界）
用户 -> API -> MySQL task + outbox -> Kafka -> inbox -> Worker领取任务
             MySQL状态/权限/attempt/租约/fence             |
                                                        v
执行层（本轮计划：一个受限 Agent，不是新服务）
              goal + task_input + 执行预算
                         |
                         v
                controller.next(observations)
                    /                 \
              Final                   ToolCall
                |                         |
                |               校验允许列表/参数/预算
                |                         |
                |               只读工具 -> 有界结果
                |                         |
                |                    回到下一决策
                v
        Mongo不可变attempt结果 + 可展示steps
                |
        MySQL有效租约/fence条件提交成功
                |
        API授权读取 -> Redis可丢弃结果缓存/Mongo
```

基础设施决定“谁执行、能否提交、如何恢复”；Agent 决策层决定“根据当前观察下一步用哪个工具或结束”。不新增编排框架、微服务、队列或数据库。

## 2. 请求与材料边界

保持现有 `POST /api/v1/tasks` 的 `{prompt}`、幂等键和结果基础字段。prompt 同时承载目标与用户粘贴的材料；内部唯一材料名是 `task_input`，内容就是本任务不可变 prompt。界面示例可写成“目标：……；材料：……”，但不得假装已经有独立附件或材料存储。

保留 prompt 1..10000字符与请求体64KiB限制，以及现有规范化和幂等摘要语义。没有额外请求字段，故无需为本轮新增 MySQL 列。未来如果添加独立材料，必须持久化并将完整规范化请求纳入幂等摘要，不能继续只摘要目标。

## 3. 单控制器与决策契约

保留 `Model.run(task)` 为服务集成入口；可新增小模块 `agent.py`、`agent_tools.py`、`agent_provider.py`，不依赖大型编排框架。

一次决策只允许以下互斥形式：

- `Final(content)`：非空且有界的最终答复。
- `ToolCall(call_id, tool_name, arguments)`：单个调用，完整校验后才执行。

内部决策对象不接受同轮多个调用、final与tool同时出现、未知动作或缺失字段。provider原始协议与内部互斥类型不同：普通assistant辅助文本与单个tool_calls同时出现是合法工具调用响应，应归一化为ToolCall，忽略且不保存该辅助文本，不误报为非法JSON。只有不存在tool_calls且finish_reason明确允许正常结束时才接受非空final；截断（如length）、明确refusal、多个调用、未知/不一致的结束原因均拒绝。不得保存provider的reasoning字段。call_id必须有界、在本attempt中唯一。工具结果反馈给控制器；下一轮可以继续选工具，也可以结束。允许第一轮直接final，不强制固定的“读→搜→统计”流水线。

- `controller_mode=scripted_test`：deterministic脚本测试策略，可根据目标和工具结果分支，用于复现执行语义。必须明确写出“无真实模型推理”，不能宣传为自主理解。
- `controller_mode=live_llm`：用户私密配置并授权后，真实模型根据观察选择工具/结束。适配器必须显式支持所选provider的工具调用协议；mock通过不代表真实provider兼容。

外部文字和工具输出均为不可信数据，不能更改系统安全规则、工具列表或预算。只记录公开动作与观察，不索要、存储或展示隐藏思维链、scratchpad、thought字段。

## 4. 三个纯只读工具

所有工具只读本任务的 `task_input`；不接受其他task_id、URL、文件路径或可执行代码。

| 工具 | 严格参数 | 有界返回 |
|---|---|---|
| `read_text` | `offset`整数≥0；`length`整数1..2000 | 文本片段、字符位置、下一位置、截断标记 |
| `search_text` | `query`非空字面字符串≤200字符；`limit`整数1..5；可选`offset`整数，默认0 | 命中位置与短片段；不是用户可控正则 |
| `numeric_stats` | `start`、`end`限定输入内的非空字符范围 | count/sum/min/max/mean；无数字时count=0且其余为null |

参数额外字段、错误类型、布尔冒充整数、越界范围均拒绝。

字符范围合法不代表序列化后满足4KiB：read/search必须按完整返回对象的实际JSON UTF-8字节数（包括转义、位置、metadata）安全裁剪文本/命中数量后再序列化；不得直接切断JSON或UTF-8字节。read_text的next_offset必须是实际已返回文本的下一字符位置，而不是原请求终点；有源文本尚未返回时truncated=true。search_text保留完整的命中位置/片段对象，并返回next_offset作为下次检索的源文本恢复位置；只有确实扫描至输入末尾且没有漏掉待返回命中时才可标记完成。因响应预算被省略的命中必须能从next_offset重新检索，不能误报读完。search_text可接受可选offset（默认0，严格限定在输入范围内），用于实际继续查询。Unicode、多字节字符和JSON转义须有边界测试。

数值工具只统计所选范围内符合显式词法规则的ASCII十进制token：`[+-]?[0-9]+(?:\.[0-9]+)?`。先扫描候选数值片段，再完整匹配，不能在不支持的片段中搜索子数字。明确的拒绝规则：范围内出现数字相邻的指数写法（如1e6、-2E-3）、数字间ASCII逗号/全角逗号（如1,000、1，000）、数字与货币符号直接相邻、NaN或Infinity时，整次工具调用返回安全的unsupported_numeric_format错误，不输出部分统计。ASCII字母/下划线相邻的数字token同样拒绝，避免把型号或指数拆开。普通空白、中文顿号、分号可分隔数列，例如`1、2、3`正常统计；`1,2,3`因逗号歧义拒绝，并提示改用空格或顿号。本轮不支持指数、千位格式、货币解析或表达式求值，示例必须覆盖拒绝而非静默拆分。最多200个数字、每个≤32字符、绝对值≤10^12。使用有限精度Decimal并确定性序列化结果；超限报错，不悄悄忽略以制造成功。日期等文本仍可能含可匹配数字，必须说明这只是词法数值统计，不是语义表格或财务解析器。

没有任意shell、文件读取、网络搜索/抓取、代码执行、上传、写入、发送消息或其他真实副作用。工具不拥有API/数据库凭据。

## 5. 预算和超时

默认硬上限（只能由受信服务配置收紧，不能由prompt放宽）：

- 每attempt最多6次决策、5次工具执行、1个final。
- 工具参数序列化≤2KiB；单工具结果≤4KiB；工具结果累计≤16KiB。
- final UTF-8≤8KiB；累计提供给provider的单次请求正文≤64KiB。
- 每次provider响应原始正文≤64KiB；每次输出token预算≤1024。字节限制与token限制都执行，不能互相代替。
- Agent执行总时间最多60秒；实际预算为 `min(60秒, lease_until - 当前时间 - 15秒持久化余量)`，不足时不启动调用。默认120秒租约不变。

时间预算在开始时转换为单调时钟截止时间，并在每轮及工具执行前后检查。live使用可取消的异步HTTP传输、总请求deadline及受限流式读取，HTTP每I/O timeout不能冒充整个请求/任务截止。超过响应大小立即停止读取。不使用无法终止的后台线程来假装取消完成，不在超时后继续发新请求。余量只用于降低过期风险，不保证数据库总能及时完成；最终仍由现有SQL有效租约/fencing条件拒绝迟到提交。

本轮不新增租约心跳、不在provider适配器内嵌套重试。不足预算、无final或超过工具/决策次数均不得返回伪造成功结果。

## 6. 错误、重试与费用

新增安全错误分类应能映射到现有永久/暂时失败机制。建议稳定code：`agent_protocol_error`、`agent_tool_rejected`、`agent_budget_exceeded`、`agent_refused`、`agent_configuration_error`、`provider_transient_error`。API仅给脱敏描述，不含原始provider响应、凭据或堆栈；持久化现有错误字段时也不得存秘密。

- 格式损坏、未知工具、参数无效、数值格式拒绝、重复call_id、空final、截断或多工具调用等协议歧义：永久错误。单工具调用附带普通assistant辅助文本不属于错误，按第3节归一化。
- 预算耗尽（含总deadline）、没有final、provider明确拒绝：永久错误。
- live未获授权、配置缺失、模式不匹配、provider协议不支持：永久错误，不自动降级为假模型答案。
- 429/5xx、网络故障或预算尚未耗尽时发生的传输超时：按现有有限attempt重试；不在同一次provider调用内另行重试。

只按现有MySQL事务机制变更状态与写DLQ；Agent不得直接裁决任务成功。保留既有SQL状态转换、claim/finalize/fencing和Redis cache-aside语义。

live继续要求明确配置的模式、`ALLOW_LIVE_MODEL`、HTTPS provider地址、模型名和私密环境key；本轮不配置、不启用、不请求用户把key粘入聊天/仓库/前端。请求会把目标和材料发送给配置的provider，需在启用说明中告知。

每个attempt最多6个决策请求；总上限为6×实际配置的attempt上限。默认MAX_ATTEMPTS=3时才是最多18个请求，18不是任意配置下的硬上限。实际费用取决于provider和token；不得承诺一次计费。外部成功但响应丢失、进程崩溃或持久化失败，都可能重放并重复付费。现有attempt结果不跨attempt复用；模型输出可能不同，单个provider请求的取消也不保证服务端停止计费。

## 7. 结果与Agent动作接口（成功后可见的MVP）

新增结果文档及results响应保留已有 `task_id/content/model_mode/cache_status` 等语义，增加：

- `execution_kind: single_agent`
- `controller_mode: scripted_test | live_llm`

新增步骤包含基础 `id/task_id/sequence/kind/content/created_at`，以及 `attempt_id/execution_kind/controller_mode`。可选 `tool_name/arguments/result/truncated` 只含有界、可公开给任务所有者的动作和结果。kind为 `tool_call/tool_result/final`；不保存完整provider消息历史或隐藏推理。稳定步骤ID由attempt_id和sequence组成。

计划新增 `GET /api/v1/tasks/{id}/agent-steps`，在读取任何缓存/文档前先SQL校验所有权。返回：

```text
{items, availability, execution_kind, controller_mode}
availability = committed | not_committed | legacy
```

- 尚无成功提交的结果：items为空，availability=not_committed，两个模式字段为null。明确不能据此断言“没有调用工具”。
- 已提交的新Agent结果：只从MySQL已提交result_id读取，返回其steps，availability=committed。
- 旧文档缺少新增元数据：返回items为空，availability=legacy；结果接口读取时补充 `execution_kind=legacy_single_call`、`controller_mode=legacy_deterministic_echo` 或 `legacy_live_single_call`（依据旧model_mode）。不要改写不可变旧文档，也不要把旧summary包装成新Agent动作。
- 已有成功引用但Mongo不可读：沿用503依赖不可用，不能伪装为空。
- 非所有者404、未登录401，规则与其他任务读接口一致。

本MVP只在最终成功后保存与显示步骤：运行中、失败attempt、进程崩溃前的工具动作不可见；不是实时轨迹、不是完整失败审计。`/events`继续表示MySQL后台生命周期；`/attempts`仍表示SQL执行尝试。未来若需失败/实时动作，另设计attempt专属Mongo集合及授权/去重/孤儿语义，不暗中扩大本轮范围。

## 8. 实施顺序与验收门槛

1. 协调者已批准此契约方向；先发布契约，等待兼容修复后的UI真实Compose/浏览器CI通过再开始实现。
2. 后端实现时同步 `docs/API_CONTRACT.md`、例子、OpenAPI与测试；不得仅实现本文而遗留接口冲突。
3. 单元：即时final、观察后选择不同下一步、工具拒绝、严格类型、数值边界、恶意材料、坏provider响应、拒绝、调用/字节/时间预算、live关闭保护、旧结果标识、无隐藏thought、资源所有权。
4. 保留核心可靠性回归；真实MySQL/Kafka/Mongo/Redis验收多步脚本执行、重复交付、Mongo失败不成功、Redis停机降级、worker恢复与过期fence拒绝、持久化刷新和新接口授权。
5. UI最小适配：区分“后台生命周期”与“Agent工具动作”；标注脚本测试/真实模型；真实空态、失败、依赖不可用与legacy提示。桌面/移动浏览器分别检查，不显示假百分比或假实时步骤。
6. 真实provider验收单独标为等待用户配置/授权；transport mock、脚本Agent和真实四组件集成均不能替代它。

仅在相应证据实际产生后更新“已实现未验收/已验收/阻塞”。本契约本身不宣称上述测试已运行。

## 9. 不在范围内

多Agent、任意工具执行、真实副作用、文件上传/对象存储、跨任务检索、向量库、新编排框架、Kubernetes、公网部署、provider自动采购或真实密钥配置。本轮不为组件名称增加基础设施。
