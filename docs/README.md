# 文档导航：从一次请求理解后端

本项目是教学用任务平台，不是生产就绪服务。先掌握一条真实调用链，再研究故障与扩展；不用同时阅读所有文件。

## 建议阅读顺序

| 顺序 | 文档 | 读完应能回答 |
|---|---|---|
| 1 | [项目入口](../README.md) | 项目解决什么问题，如何启动和安全停止？ |
| 2 | [开发任务清单](DEVELOPMENT_PLAN.md) | 当前已验证什么，下一轮做什么，怎样才算完成？ |
| 3 | [架构与调用链](ARCHITECTURE.md) | 请求怎样经过 API、MySQL、Kafka、Worker、MongoDB 和 Redis？ |
| 4 | [模块功能契约](MODULE_CONTRACTS.md) | 每个模块负责什么、不负责什么，出错后谁处理？ |
| 5 | [学习路线](LEARNING_PATH.md) 与 [组件地图](COMPONENTS.md) | 应先看哪些代码，每个组件为什么需要？ |
| 6 | [API 契约](API_CONTRACT.md) | 注册、会话、CSRF、幂等和资源权限怎样配合？ |
| 7 | [故障实验](FAILURE_LABS.md) | 停掉缓存、消息系统或结果库后，哪些行为应该改变？ |
| 8 | [Agent 逐步导读](AGENT_WALKTHROUGH.md) | 控制器、工具、观察结果与后台生命周期有何不同？ |
| 9 | [外部学习资料](OPEN_SOURCE_RESOURCES.md) | 去哪里读上游原文，如何对应本仓库练习？ |

## 按任务查找

- 改后端之前：[Agent.md](../Agent.md)、[API 契约](API_CONTRACT.md)、[架构决策 ADR](adr/001-modular-monolith.md)。
- 配置与凭据：[配置说明](CONFIGURATION.md)。默认不启用真实模型，已有数据卷不能靠随机补密码修复。
- 运行与排障：[Compose 环境](../infra/README.md)、[故障实验](FAILURE_LABS.md)、[运维与恢复边界](OPERATIONS.md)。备份恢复步骤尚未实跑，不能当作灾备能力。
- 参与贡献：[贡献指南](../CONTRIBUTING.md)、[安全报告](../SECURITY.md)、[第三方许可与来源](THIRD_PARTY_NOTICES.md)、[发布核对表](RELEASE_CHECKLIST.md)。项目许可证仍待维护者选择。
- 打开可选前端：[学习界面指南](UI_GUIDE.md)。界面显示的是后端证据，不是另一套任务状态。
- 理解模型边界：[单 Agent 契约](SINGLE_AGENT.md)。默认脚本模式不是语言理解；真实模型连通性不等于完整 Agent 链路验收。
- 查看已执行证据：[单 Agent 验收](AGENT_TEST_REPORT.md)、[界面验收](UI_TEST_REPORT.md)、[当前开发任务状态](DEVELOPMENT_PLAN.md)。历史报告只证明其标明的提交，不自动代表后续版本。
- 了解部署层：[Kubernetes 草稿](../infra/k8s/README.md)。目前未做真实集群验收，也不是默认启动依赖。

## 阅读时区分四种状态

1. **有代码**：能找到实现，不代表行为已验证。
2. **单元或静态检查通过**：证明部分契约，不代表真实组件连接成功。
3. **真实集成通过**：以明确提交和 CI 结果为证，仍不等于生产高可用或全面安全认证。
4. **计划/草稿**：不能拿来宣称系统已经具备该能力。

文档中的命令要结合各自前提执行。不得把 `.env`、Cookie、CSRF token、连接密码、模型密钥或完整容器配置贴进公开 Issue；普通停止不删除数据卷。外部资料只作有出处的导读和链接汇总，上游许可与本项目许可互不替代。
