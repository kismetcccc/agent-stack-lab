# Agent Stack Lab

**打开组件操作台，直接学习 MySQL 增删改查、Redis 键值与过期、MongoDB JSON 文档、Kafka 发送与实际收取。**

中文后端教学项目：FastAPI / MySQL / Redis / MongoDB / Kafka。**不必先创建 Agent 任务，不需要模型 Key，也不调用真实模型。** 原任务与 Agent、架构说明保留为进阶入口。

> **当前改版**：按[本地控制台计划](docs/CONSOLE_REDESIGN_PLAN.md)重整导航和操作区，云端完整 CI 与实际截图已通过，2026-10-23 本机已更新到 `11bdeb5f`，七服务健康，配置与业务数据保留，见[本轮验收状态](docs/CONSOLE_REDESIGN_REPORT.md)。PNL07：云端通过；本机部署和主要交互通过，剩余本机覆盖待补；任务抽屉本机步骤及认证阶段完整浏览器错误记录未验收。
>
> **已完成组件操作台**：代码 `ec1126d2` 的完整 CI 与本机升级已验收，595 项后端、58 项前端单元、20 项真实集成和 38 项浏览器测试见[历史报告](docs/COMPONENT_PLAYGROUND_REPORT.md)。这些结果不替代本轮界面回归。独立模型连通性不等于完整 live Agent 验收，本项目不是生产就绪平台。

## 先选一个组件，动手试一次

| 操作台 | 你做什么 | 看什么才算有证据 |
|---|---|---|
| **MySQL** | 创建记录 → 读取 → 修改 → 确认删除 | 服务端 ID、内容和更新时间；刷新后重新从数据库读取 |
| **Redis** | 写一个值和 10 秒 TTL → 再次读取 | 实际值、服务器 PTTL 快照；新读取确认键不存在才证明当时已不存在 |
| **MongoDB** | 保存 JSON 对象 → 读取 → 完整替换 → 确认删除 | 独立教学 collection 回读的文档，不是编辑器草稿 |
| **Kafka** | 发送一条消息 → 查看两栏状态 | 「生产确认」与「消费者收取」分别来自 broker 确认和 Worker 实际消费回执 |

**数据是本机共享的**：所有已登录本地账号看到同一批教学数据，不做账号/租户隔离。仍保留登录、CSRF、Origin；旧任务仍按原所有权访问。教学数据与任务、账号、结果分开，不要写入秘密或重要资料。没有原始 SQL/命令控制台、任意 topic、批量清库或 Kafka 重放。

从[一步一步的组件操作台教程](docs/COMPONENT_PLAYGROUND_GUIDE.md)开始：每个练习都有输入示例、按钮和预期可见变化。

## 打开界面

需要 Docker Engine/Desktop、Compose v2；首次初始化还需要 Python 3。以下供已获授权的本地学习环境执行，不表示本次已替你启动。

**全新目录、没有 `.env` 且没有待保留数据卷**，才先运行：

```bash
python scripts/infra-init-env.py
```

已有 `.env` 或忽略的 `.env.compose.local` 必须保留；不要重新生成已有数据库密码，也不要复制云端配置覆盖本机。已有栈更新先读[保留数据的升级步骤](docs/OPERATIONS.md#组件操作台的保留数据更新)。

使用默认 `.env` 的学习栈：

```bash
docker compose -f compose.yaml -f compose.ui.yaml up -d --build --wait --wait-timeout 300
```

打开 **http://localhost:8081/**，登录后进入组件操作台。使用已有账号即可；四个实验不以任务为前置。同源接口文档在 **http://localhost:8081/docs**。必须保持 `localhost:8081`，不要与 `127.0.0.1` 或 8080 浏览器写请求混用，详见[界面指南](docs/UI_GUIDE.md)。

普通停止保留数据卷：

```bash
docker compose -f compose.yaml -f compose.ui.yaml down
```

不要加删卷选项。修改 `.env` 的密码不会自动修改已初始化数据库。不要分享完整 `docker compose config` 输出，因为它可能展开密码。

## 只启动后端

已有正确开发配置时：

```bash
docker compose up -d --build --wait --wait-timeout 300
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8080/readyz
```

默认单文件 Compose 入口 **8080 是 API，不是前端页面**；OpenAPI 在 `http://localhost:8080/docs`。显式迁移 `python -m backend.migrate` 成功后 Compose 才启动 API/Worker；API 自身不建表。当前版本区分 **HTTP API v1、MySQL schema v2、Kafka lab envelope v1**，不是三个同义版本号。v1→v2 只追加独立教学表，不等于通用自动升级/降级、备份恢复或高可用。

数据库不向主机公开端口，入口仅绑定 loopback；单节点开发配置不是公网安全方案。已有模型配置但开发凭据不完整时，先读[配置说明](docs/CONFIGURATION.md)，不要用随机新密码“修复”已有数据卷。

## 哪些“真实”需要分开看

| 设置或观察 | 含义与边界 |
|---|---|
| `LAB_MODE=production` | 使用真实组件适配器；名字不代表生产安全或每次操作成功 |
| `LAB_MODE=test/demo` | 显式测试/演示替身，不能作为真实四组件证据 |
| `MODEL_MODE=deterministic` | 旧 Agent 使用脚本测试控制器；不是 LLM 推理，操作台本身不调用模型 |
| Kafka `acknowledged` | broker 确认发送，不等于消费者收取；`unconfirmed` 也不证明绝未投递 |
| Redis TTL 倒计时 | 仅供估算；实际过期/缺失只能由新的服务端读取确认 |

默认 Compose 固定 deterministic，也不转发 live 所需变量；只在 `.env` 填 Key 不会启用真实模型。新操作台不需要更改模型设置。Kubernetes、公网部署、高可用与灾备均没有本轮验收承诺。

## 继续学习或修改代码

1. [组件操作台教程](docs/COMPONENT_PLAYGROUND_GUIDE.md)：先直接操作四个组件。
2. [文档导航](docs/README.md)：按使用、接口、配置、运维查找。
3. [API 契约](docs/API_CONTRACT.md)与[模块契约](docs/MODULE_CONTRACTS.md)：把可见行为对应到后端。
4. [Agent.md](Agent.md)与[本轮冻结计划](docs/COMPONENT_PLAYGROUND_PLAN.md)：修改代码前的边界和验收门槛。
5. [旧任务架构](docs/ARCHITECTURE.md)、[Agent 导读](docs/AGENT_WALKTHROUGH.md)、[故障实验](docs/FAILURE_LABS.md)：可选进阶，不是操作台前置课程。
6. [官方与开源资料索引](docs/OPEN_SOURCE_RESOURCES.md)：带出处的上游阅读入口，不复制第三方文档充当本项目实现。

代码存在、离线测试、真实组件集成、真实浏览器、用户本机更新是不同证据层级；以对应提交报告为准。公共仓库不得包含密钥、真实个人资料、数据库卷或私有日志。

## 贡献与许可边界

仓库公开不等于已经授予开源许可。当前项目许可证尚待维护者明确选择；外部组件与参考资料保留各自许可，不因本项目引用而改变。学习资料入口见[文档导航](docs/README.md)。
