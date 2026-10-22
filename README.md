# Agent Stack Lab

**用一个任务平台，学习一次后端请求如何经过 API、数据库、消息系统和后台执行器。**

中文后端教学项目：FastAPI / MySQL / Kafka / MongoDB / Redis。Docker Compose 是真实集成载体，不用容器数量冒充架构能力。

> **后端学习版本已验证**：提交 `f36523fa` 在 [GitHub Actions](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39725461902) 通过 145 项后端/采集器测试、13 项真实组件集成、30 项前端单元和 30 项桌面/手机浏览器测试。自动 CI 使用明确标注的脚本控制器；测试执行成功不等于自然语言任务质量合格。真实模型仅做过独立接口连通性检查，**尚无完整 live Agent 链路验收**。Kubernetes 和公网部署未验收，本项目不是生产就绪平台。

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

先看 [文档导航](docs/README.md) 与 [开发任务清单](docs/DEVELOPMENT_PLAN.md)。当前优先级是各后端模块的功能、调用链、故障行为和学习文档，不扩大细粒度 AI 评分或堆叠新组件。

1. [Agent.md](Agent.md)：第一份项目文件，架构与实施约束。
2. [架构与代码阅读](docs/ARCHITECTURE.md)：每条箭头、数据权威和一次任务的生命周期。
3. [学习路线](docs/LEARNING_PATH.md)：按章节理解，不一次背完组件。
4. [组件地图](docs/COMPONENTS.md)：为什么用，不用会怎样，以及尚未实现的能力。
5. [故障实验](docs/FAILURE_LABS.md)：用故障检验设计，而不是只看正常截图。
6. [API 契约](docs/API_CONTRACT.md)：前后端接口的唯一详细定义。
7. [单Agent逐步导读](docs/AGENT_WALKTHROUGH.md)：从提交文本到工具观察、结果提交与显示。
8. [ADR](docs/adr/001-modular-monolith.md)：记录重要选择和代价。

## 当前聚焦：模块功能与可选学习界面

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
                  Worker executor → 单Agent控制器/只读工具循环 → MongoDB 结果
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
| `MODEL_MODE=deterministic` | 脚本测试控制器与受限工具循环，不是真实模型推理，不产生模型调用费用 |
| `MODEL_MODE=live` | 需额外显式启用及模型配置；未经配置不自动调用 |

因此“真实四组件集成＋确定性模型”是有效的基础设施测试，但不是“真实模型调用已经验收”。真实模型凭据只能通过私密配置提供，不要提交到公共仓库。**默认 Compose 硬编码 deterministic，且没有转发 live 所需变量；只在 `.env` 填入 Key 不会启用容器内的真实模型。** 后续显式接入必须同时核对 API/Worker 模式、重试与调用预算，参见开发任务清单。

## 完成度与限制

首轮交付包含接口、会话/CSRF、任务幂等、状态机、事务 Outbox/Inbox、租约重试和四组件适配器；前端另有独立构建和浏览器验收，部署扩展本轮继续暂停。**代码存在、静态检查通过、真实集成通过是三个不同层级**，最终验收报告需给出所测 commit 和检查结果。

当前重点限制：单 relay/worker 起步；认证没有邮件验证、找回、MFA；单Agent只开放三个纯只读文本工具，完整真实模型任务链路尚未验收；没有任意操作、长期聊天记忆、多Agent、RAG、对象存储、外部搜索或持久化定时调度；日志/指标/trace 分别验收；没有高可用和灾备承诺。不要将开发模式 `production` 字样理解为安全认证。

本项目不提交密钥、真实个人资料、数据库卷或私有日志。请先阅读 [Agent.md](Agent.md) 再修改代码。

## 贡献与许可边界

仓库公开不等于已经授予开源许可。当前项目许可证尚待维护者明确选择；外部组件与参考资料保留各自许可，不因本项目引用而改变。学习资料入口见 [文档导航](docs/README.md)。
