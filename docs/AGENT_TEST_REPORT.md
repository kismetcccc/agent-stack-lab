# 受限单 Agent 验收报告

日期：2026-10-22。被测代码：`9c4a1908124b61eee4207dc5bb6cb172134fda06`。

[GitHub Actions 39721645077](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39721645077) 三个job全部成功。源码、接口、真实基础设施、前端和浏览器均在这一精确提交上检查。默认控制器为scripted_test；**真实LLM/provider兼容性与费用未验收**。

## 1. 实际执行结果

| 检查 | 结果 |
|---|---|
| Python单元/API/工具/provider模拟协议 | 140通过 |
| 后端Ruff与构建/配置检查 | 通过 |
| MySQL/Kafka/MongoDB/Redis真实主链路与API | 11通过 |
| 真实租约恢复、fencing与有限重试 | 2通过 |
| Redis/Kafka/Mongo停机、Worker替换、有限秘密模式日志扫描 | 通过 |
| 前端类型检查、构建与单元 | 30通过 |
| 桌面1440px、手机390px真实浏览器 | 24通过 |
| 最终视觉复核 | 两种尺寸的真实Agent动作页面通过，生命周期/工具动作分开，无横向裁切 |

独立解析下载的JUnit：浏览器24、集成11、恢复2，均为0 failure、0 error、0 skipped。浏览器使用官方Chromium151及Playwright1.62.1，sandbox开启，零重试；不使用force点击或伪造业务响应。

job标识：checks `119636223710`；compose `119636330392`；frontend `119636223862`。

## 2. 证据与可重查来源

在上述run的Artifacts中：

- UI artifact `12401338075`，下载ZIP SHA256：`7f43114bf677da1b06d89accb2dba29b4f6e7e88d73b7cb266563ac0f81fd3a1`。
- 真实集成artifact `12401437064`，下载ZIP SHA256：`df58d73d5279a09732b5b09b05417e38d6e1904639cc4f20570f844b86f70838`。
- 新动作截图名称为 `desktop-chromium-single-agent-actions.png`、`mobile-chromium-single-agent-actions.png`；它们来自真实API/四组件服务，而不是静态演示。

本次截图含公开的XSS样式测试文本，以验证纯文本渲染；不代表脚本被执行。未将真实凭据、.env、Cookie、CSRF、浏览器trace/video/storageState加入交付物或artifact。

## 3. 核心断言

### 受限执行而非任意工具

- 三个只读工具仅访问当前prompt：read_text、search_text、numeric_stats；严格类型、额外参数、范围和预算检查。
- 观察后分支、立即final、未知工具、多调用、重复ID、拒绝、截断响应、无final、字节/步骤/总时间上限均有离线测试。
- live传输用mock验证请求、响应、取消与关闭流；不包含真实provider调用，不证明所有供应商兼容。
- 独立代码审查另做100组Unicode/转义文本的搜索分页检查，验证有界JSON、完整命中与正确前进位置；此检查不计入上表140项持久测试。

### 真实持久化与权限

- 示例产生read/search/stats三对动作及final，共7步；count=3、sum="60"、mean="20"。
- SQL权威状态/结果引用、Mongo不可变attempt结果、Redis缓存与Kafka重复交付真实验证；不把Mongo孤儿或旧fence结果暴露为成功。
- `/agent-steps`先验证SQL所有权；未登录401、他人404；未提交/失败返回明确not_committed，不能误读为空执行。
- 两种旧模型结果被标为legacy且不改写Mongo；存在但损坏的新元数据不是旧结果，安全返回503。
- Mongo读不可用且Redis未命中时，动作接口503；恢复后可读。Redis停机不成为任务状态权威。

### 真实界面

- 保留原18场景，并新增3场景×两种视口：动作与真实API逐项一致、安全文本及刷新/缓存/退出；失败时诚实空态；迟到旧动作不能覆盖新任务。
- 每一步的id、工具参数JSON、结果JSON与final文本和真实API对照，不仅检查“页面看起来有步骤”。
- 确定性脚本明显标识“无真实模型推理”；SQL后台生命周期与成功后工具动作分区。手机宽度严格对照390px，任务列表与详情终态/attempt一致。

## 4. 审查期间发现并修复

非法工具JSON中非有限数值或孤立Unicode代理字符曾可能在编码时抛出普通异常，被误判成暂时故障。现已在provider解码和runtime编码处转换为安全永久拒绝，并加入回归，避免无意义重复模型请求。HTTP输入相应非法Unicode已有422处理，也补充了回归。

另修正元数据兼容边界：只有两个新字段都缺失才是legacy；缺一个、null或未知值均不能伪装成旧版执行类型。所有修复包含在本次被测提交中。

前端先前沙箱运行环境、手机网格与列表旧状态问题见 [UI_TEST_REPORT.md](UI_TEST_REPORT.md)，本次24浏览器测试再次覆盖原有流程。

## 5. 不能从这些通过结果推导什么

- 不是生产安全认证；没有公网部署、高可用、灾备、生产压测、邮件验证、密码找回或MFA验收。
- 没有真实模型推理、真实provider兼容/额度/计费验收，没有多Agent、任意shell/文件/URL工具、外部副作用、长期聊天记忆、RAG或Kubernetes实现。
- 工具动作只在最终成功提交后持久化可见；不是实时轨迹，也不是失败/崩溃前的完整审计。
- 最多6个provider请求/attempt；任务重试、响应丢失或持久化失败仍可能重复计费。取消客户端等待不保证provider停止计费。
- 锁文件未变，本轮未重新执行npm audit；不把此前零漏洞结果当作永久安全保证。CI安装显式不执行隐式audit。
- 本报告只证明这一代码快照；后续功能更改必须重新验证。

学习入口：[逐步调用导读](AGENT_WALKTHROUGH.md)、[API契约](API_CONTRACT.md)、[单Agent边界](SINGLE_AGENT.md)、[本地启动](UI_GUIDE.md)。
