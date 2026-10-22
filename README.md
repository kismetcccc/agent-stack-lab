# Agent Stack Lab

**用一个 Agent 任务平台，学习一条请求如何经过前端、API、数据库、消息系统和后台执行器。**

中文后端教学项目：FastAPI / MySQL / Kafka / MongoDB / Redis。Docker Compose 是真实集成载体，不用容器数量冒充架构能力。

> **当前边界**：代码与部署脚本正在完成首轮验收。云端开发环境没有 Docker；Compose 和 Kind 的运行结果必须以实际 CI 记录为准，不能从配置文件存在推断成功。默认 `deterministic` 模式不调用真实模型，不是完整自主 Agent。项目不是生产就绪平台，不应直接暴露公网。

## 不熟悉这些组件？先看一个小例子

你提交“帮我解释一段资料”，系统稍后给出结果，就像点餐后拿到取餐号。

- **API像接单窗口**：检查输入、确认你是谁，给你task_id；不会让你一直等到工作完成。
- **MySQL像订单账本**：记录谁的任务、是否完成；重启后还能查询。
- **Kafka像传单通道**：把“有新任务”交给后台；它不是查询订单当前状态的账本。
- **Worker像实际干活的人**：领取任务，调用文本/模型处理，把结果保存。
- **MongoDB像成果档案袋**：装本次执行的结果和不同形状的步骤信息。
- **Redis像临时状态看板**：显示短期进度；看板坏了不能把账本里的任务也弄丢。

先记住这六句话，不必马上理解Outbox、Inbox、租约和fencing。后面的章节才解释它们分别防哪一种故障。**把整套服务运行起来，不代表必须一次理解全部。**

## 从哪里开始

1. [Agent.md](Agent.md)：第一份项目文件，架构与实施约束。
2. [架构与代码阅读](docs/ARCHITECTURE.md)：每条箭头、数据权威和一次任务的生命周期。
3. [学习路线](docs/LEARNING_PATH.md)：按章节理解，不一次背完组件。
4. [组件地图](docs/COMPONENTS.md)：为什么用，不用会怎样，以及尚未实现的能力。
5. [故障实验](docs/FAILURE_LABS.md)：用故障检验设计，而不是只看正常截图。
6. [API 契约](docs/API_CONTRACT.md)：前后端接口的唯一详细定义。
7. [ADR](docs/adr/001-modular-monolith.md)：记录重要选择和代价。

## 当前聚焦：先把后端理清楚

**当前只做 API、MySQL、Kafka、MongoDB、Redis 的后端闭环。前端和新增外围组件暂停。** Kubernetes 仅保留后续学习章节，不是当前验收目标。之前产生的前端/部署实验文件不表示它们已完成或本轮继续展开。

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

## 后端启动（需在有 Docker 的环境验收）

要求 Docker Engine/Desktop 和 Compose v2、Python 3；Windows 建议 WSL2。命令已与基础设施负责人核对，**当前云端没有 Docker，真实运行以 CI 对应 commit 的记录为准**。

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

外围组件、前端和 Kind 本轮不启动；后续再独立核对启动说明与资源预算。

## 两条互相独立的“真实”维度

| 设置 | 含义 |
|---|---|
| `LAB_MODE=production` | 选择真实 MySQL/Kafka/MongoDB 等适配器；名字不代表生产级质量 |
| `LAB_MODE=test/demo` | 测试/演示替身，不能作为真实基础设施集成证据 |
| `MODEL_MODE=deterministic` | 确定性文本处理，不产生模型调用费用 |
| `MODEL_MODE=live` | 需额外显式启用及模型配置；未经配置不自动调用 |

因此“真实四组件集成＋确定性模型”是有效的基础设施测试，但不是“真实模型调用已经验收”。用户后续提供模型 API 时，应通过私密环境配置设置，不要提交到公共仓库；具体开关以 `backend/config.py` 和后续模型接入说明为准。

## 完成度与限制

首轮交付包含接口、会话/CSRF、任务幂等、状态机、事务 Outbox/Inbox、租约重试和四组件适配器，；前端与部署扩展本轮暂停。**代码存在、静态检查通过、真实集成通过是三个不同层级**，最终验收报告需给出所测 commit 和检查结果。

当前重点限制：单 relay/worker 起步；认证没有邮件验证、找回、MFA；模型仅做受限文本处理；尚无完整工具规划、RAG、对象存储、搜索或持久化定时调度；日志/指标/trace 分别验收；没有高可用和灾备承诺。不要将开发模式 `production` 字样理解为安全认证。

本项目不提交密钥、真实个人资料、数据库卷或私有日志。请先阅读 [Agent.md](Agent.md) 再修改代码。
