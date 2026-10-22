# 文档导航：先直接操作，再按需深入

先在组件操作台保存一条记录、观察一个键过期、修改一份 JSON、收取一条 Kafka 消息。**无需先创建任务或理解整条 Agent 链路。** 这是个人本地共享教学工具，不是生产平台。

本轮实施状态见[控制台改版计划](CONSOLE_REDESIGN_PLAN.md)与[改版验收记录](CONSOLE_REDESIGN_REPORT.md)。已完成的[组件操作台验收](COMPONENT_PLAYGROUND_REPORT.md)保留为历史，不代替新版 UI 测试。

## 建议阅读顺序

| 顺序 | 文档 | 读完能做什么 |
|---|---|---|
| 1 | [项目入口](../README.md)与[界面启动](UI_GUIDE.md) | 保留配置，打开 localhost:8081 |
| 2 | [组件操作台逐步教程](COMPONENT_PLAYGROUND_GUIDE.md) | 点按钮完成四个独立小实验，辨别真实证据 |
| 3 | [API 契约](API_CONTRACT.md) | 把输入、输出、错误与 `/api/v1/lab` 对上 |
| 4 | [模块功能契约](MODULE_CONTRACTS.md) | 理解存储边界、失败交接与实现入口 |
| 5 | [配置说明](CONFIGURATION.md)与[运维说明](OPERATIONS.md) | 分清配置来源、迁移和非破坏性恢复 |
| 6 | [架构与调用链](ARCHITECTURE.md)、[Agent 导读](AGENT_WALKTHROUGH.md) | 可选：再研究旧任务、Outbox/Inbox 和 Agent |
| 7 | [学习路线](LEARNING_PATH.md)、[组件地图](COMPONENTS.md)、[故障实验](FAILURE_LABS.md) | 可选：在独立合成环境研究后端可靠性 |
| 8 | [官方与开源学习资料](OPEN_SOURCE_RESOURCES.md) | 对照上游原文继续学，不把引用当实现证据 |

## 按任务查找

- **本轮范围与状态**：[控制台改版计划](CONSOLE_REDESIGN_PLAN.md)，首发 `5d19a9b402dc4a194b485e70e8192a818243e6cb`。它保留计划发布时的快照；是否验收必须看对应提交和实际结果，不把计划文案当运行状态。
- **数据边界**：新 lab 数据本机共享；仍需登录/CSRF/Origin；旧任务所有权不变。HTTP API v1、SQL schema v2、Kafka envelope v1 是三个独立版本。
- **改后端之前**：[Agent.md](../Agent.md)、[API 契约](API_CONTRACT.md)、[架构决策 ADR](adr/001-modular-monolith.md)。
- **配置与凭据**：[配置说明](CONFIGURATION.md)。保留 `.env` 与忽略的 `.env.compose.local`，不新增模型 Key；已有卷不能靠随机补密码修复。
- **已有本机栈更新**：[保留数据的升级步骤](OPERATIONS.md#组件操作台的保留数据更新)、[Compose 环境](../infra/README.md)。云端 CI 与本机验收分开；每个新版仍须单独保留数据更新并核验。
- **历史证据**：[学习型 v1 清单](DEVELOPMENT_PLAN.md)、[开发报告](DEVELOPMENT_REPORT.md)、[单 Agent 验收](AGENT_TEST_REPORT.md)、[界面验收](UI_TEST_REPORT.md)。保留其原提交与测试数，不充当新 lab 验收。
- **模型与部署限制**：[单 Agent 契约](SINGLE_AGENT.md)、[Kubernetes 草稿](../infra/k8s/README.md)。独立 provider 连通性不是 live 全栈验收；Kubernetes 不是默认依赖。
- **参与贡献**：[贡献指南](../CONTRIBUTING.md)、[安全报告](../SECURITY.md)、[第三方许可与来源](THIRD_PARTY_NOTICES.md)、[发布核对表](RELEASE_CHECKLIST.md)。

## 阅读证据时分清层级

有代码 ≠ 离线测试通过 ≠ 真实组件通过 ≠ 浏览器通过 ≠ 用户本机已更新。报告应给出提交、实际命令、真实依赖或替身，以及通过/失败/未运行；旧版本绿色结果不自动覆盖新增功能。

不公开 `.env`、cookie、CSRF、连接密码、模型密钥或完整容器配置；共享 lab 不存秘密。普通停止不删除卷，删除教学数据也只确认单条。备份恢复手册仍不是已经验收的灾备能力。
