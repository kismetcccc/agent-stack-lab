# Agent Stack Lab

**用一个任务平台，学习一次后端请求如何经过 API、数据库、消息系统和后台执行器。**

中文后端教学项目：FastAPI / MySQL / Kafka / MongoDB / Redis。Docker Compose 是真实集成载体，不用容器数量冒充架构能力。

> **已验证**：提交 `382da456` 在 [GitHub Actions](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39720266829) 通过20项后端单元/API、9项真实组件测试、17项前端单元和18项桌面/移动浏览器测试。详见 [UI验收报告](docs/UI_TEST_REPORT.md) 与 [首轮后端报告](docs/TEST_REPORT.md)。四个存储/消息组件均真实运行；模型仍为deterministic，不产生真实模型调用。受限单Agent已按 [先行契约](docs/SINGLE_AGENT.md) 实现，新增真实链路仍待独立验收。Kubernetes继续延期；项目不是生产就绪平台，不应直接暴露公网。

## 不熟悉这些组件？先看一个小例子

你提交“帮我解释一段资料”，系统稍后给出结果，就像点餐后拿到取餐号。

- **API像接单窗口**：检查输入、确认你是谁，给你task_id；不会让你一直等到工作完成。
- **MySQL像订单账本**：记录谁的任务、是否完成；重启后还能查询。
- **Kafka像传单通道**：把“有新任务”交给后台；它不是查询订单当前状态的账本。
- **Worker像实际干活的人**：领取任务，调用文本/模型处理，把结果保存。
- **MongoDB像成果档案袋**：装本次执行的结果和不同形状的步骤信息。
- **Redis像临时看板和复印件柜**：保存短期进度，缓存已完成结果，重复查询少访问 MongoDB；缓存丢了也不能把账本里的任务弄丢。

先记住这六句话，不必马上理解Outbox、Inbox、租约和fencing。后面的章节才解释它们分别防哪一种故障。**把整套服务运行起来，不代表必须一次理解全部。**

## 从哪里开始

1. [Agent.md](Agent.md)：第一份项目文件，架构与实施约束。
2. [架构与代码阅读](docs/ARCHITECTURE.md)：每条箭头、数据权威和一次任务的生命周期。
3. [学习路线](docs/LEARNING_PATH.md)：按章节理解，不一次背完组件。
4. [组件地图](docs/COMPONENTS.md)：为什么用，不用会怎样，以及尚未实现的能力。
5. [故障实验](docs/FAILURE_LABS.md)：用故障检验设计，而不是只看正常截图。
6. [API 契约](docs/API_CONTRACT.md)：前后端接口的唯一详细定义。
7. [ADR](docs/adr/001-modular-monolith.md)：记录重要选择和代价。

## 当前聚焦：用可选界面理解后端

**后端闭环和可选学习前端已完成真实验收，帮助理解 API、MySQL、Kafka、MongoDB、Redis。** Kubernetes 和新增外围组件继续延期。前端不改变任务状态的权威来源，也不伪造消息流或组件在线状态。

界面启动、功能边界和学习顺序见 [学习界面指南](docs/UI_GUIDE.md)。在已创建本地 `.env` 的前提下：

```bash
docker compose -f compose.yaml -f compose.ui.yaml up -d --build --wait --wait-timeout 300
```

打开 **http://localhost:8081/**。默认后端单独运行仍使用8080，二者的Origin配置区别见指南。

```text
curl / HTTP客户端 → API → MySQL（任务状态的账本）
                            ↓ 同一事务中的 Outbox
                       Worker relay → Kafka
                                        ↓
                  MySQL Inbox / ready ← Worker consumer
                            ↓
                  Worker executor → 文本/模型适配器 → MongoDB 结果
                            ↓ 验证租约与fence后提交
                       MySQL succeeded
```

Redis 保存可失效的进度提示和不可变结果缓存，不决定任务是否完成。`progress` 是阶段值，不是模型完成的精确百分比。先读[逐步调用导读](docs/ARCHITECTURE.md)，再做[curl实验](docs/FAILURE_LABS.md)。

## 后端启动（Compose 链路已在 CI 验证）

要求 Docker Engine/Desktop 和 Compose v2、Python 3；Windows 建议 WSL2。以下流程已在 Linux GitHub Actions 的真实 Docker 环境执行；你的本地环境仍须满足这些前提。当前未宣称完成 Windows Docker 或 Kubernetes 验收。

```bash
python scripts/infra-init-env.py
# .env 已存在会拒绝覆盖；不要为消除提示删除已有凭据。
docker compose up -d --build --wait --wait-timeout 300
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8080/readyz
```

API 文档：`http://localhost:8080/docs`。默认8080直接访问API，不是前端页面。注册与提交任务见[curl实验](docs/FAILURE_LABS.md)。数据库不对主机公开端口，没有默认帐号。初始化只生成私有开发凭据，不包含真实模型key。

```bash
# 真实服务业务与故障测试（先启动core）
bash scripts/test-integration.sh
# 普通停止，保留命名数据卷
docker compose down
```

**`docker compose down -v` 会删除数据卷，不是普通停止。** 修改.env中的密码不会自动更新已初始化数据库。不要将完整 `docker compose config` 输出上传到公共日志，因为它可能展开密码。

上述单文件命令只启动后端；学习前端须显式使用 UI 覆盖配置。外围组件和 Kind 本轮不启动。

## 两条互相独立的“真实”维度

| 设置 | 含义 |
|---|---|
| `LAB_MODE=production` | 选择真实 MySQL/Kafka/MongoDB 等适配器；名字不代表生产级质量 |
| `LAB_MODE=test/demo` | 测试/演示替身，不能作为真实基础设施集成证据 |
| `MODEL_MODE=deterministic` | 确定性文本处理，不产生模型调用费用 |
| `MODEL_MODE=live` | 需额外显式启用及模型配置；未经配置不自动调用 |

因此“真实四组件集成＋确定性模型”是有效的基础设施测试，但不是“真实模型调用已经验收”。用户后续提供模型 API 时，应通过私密环境配置设置，不要提交到公共仓库；具体开关以 `backend/config.py` 和后续模型接入说明为准。

## 完成度与限制

首轮交付包含接口、会话/CSRF、任务幂等、状态机、事务 Outbox/Inbox、租约重试和四组件适配器；前端另有独立构建和浏览器验收，部署扩展本轮继续暂停。**代码存在、静态检查通过、真实集成通过是三个不同层级**，最终验收报告需给出所测 commit 和检查结果。

当前重点限制：单 relay/worker 起步；认证没有邮件验证、找回、MFA；模型仅做受限文本处理；尚无完整工具规划、RAG、对象存储、搜索或持久化定时调度；日志/指标/trace 分别验收；没有高可用和灾备承诺。不要将开发模式 `production` 字样理解为安全认证。

本项目不提交密钥、真实个人资料、数据库卷或私有日志。请先阅读 [Agent.md](Agent.md) 再修改代码。
