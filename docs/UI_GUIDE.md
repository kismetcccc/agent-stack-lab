# 学习界面：直接操作四个后端组件

主入口是**组件实验台**：MySQL、Redis、MongoDB、Kafka 各有自己的输入、按钮和真实响应。不必先创建 Agent 任务；「任务与 Agent」「架构说明」「学习路径」保留为次级入口。详细点击练习见[组件操作台教程](COMPONENT_PLAYGROUND_GUIDE.md)。

## 启动与已有栈更新

需要 Docker、Compose v2。仅全新目录、没有 `.env`、没有待保留数据卷时运行：

```bash
python scripts/infra-init-env.py
```

已有 `.env` 保留不动；使用独立 `.env.compose.local` 的本机栈继续沿用它，不生成新密码、不复制云端 `.env`。已有 v1 栈必须先按[保留数据更新](OPERATIONS.md#组件操作台的保留数据更新)执行显式 schema v2 迁移；云端 CI 不等于本机已经更新。

使用默认 `.env` 的学习栈启动：

```bash
docker compose -f compose.yaml -f compose.ui.yaml up -d --build --wait --wait-timeout 300
```

- 页面：**http://localhost:8081/**；同源 OpenAPI：**http://localhost:8081/docs**。
- 仅 `compose.yaml` 仍是后端 8080，不会启动 UI。
- overlay 固定 `APP_ORIGIN=http://localhost:8081`；`localhost`、`127.0.0.1`、8080 是不同 Origin。启用 UI 后不要从 8080 Swagger 发浏览器写请求。
- 仅绑定回环地址，不是公网部署方案；不需要模型 Key。

普通停止保留数据卷：

```bash
docker compose -f compose.yaml -f compose.ui.yaml down
```

不要添加删卷选项。不同配置文件/项目名不能混用，详见[配置说明](CONFIGURATION.md)。

## 页面入口与数据边界

| 页面地址（8081 后的 hash） | 内容 |
|---|---|
| `#playground`（默认） | 四张直接操作卡片与共享数据提示 |
| `#mysql` | 固定记录 CRUD |
| `#redis` | 指定 key 的值与真实 TTL 观察 |
| `#mongo` | JSON 文档 CRUD |
| `#kafka` | 消息发送、历史与两种观察状态 |
| `#lab` | 原有任务与 Agent，仍有任务所有权检查 |
| `#overview` / `#learn` | 架构说明 / 学习路径，都是可选教学内容 |

所有新实验继续要求现有登录。没有新增租户或账号隔离：所有已登录本地账号共享 lab 数据，不存放隐私、密码、模型 Key 或重要资料。新存储与原任务/账号/结果分离；删除前展示具体对象并确认。取消、Esc 或切换页面不应发送删除请求；已经提交的写操作不能靠切页撤销。

## 读懂可见状态

- MySQL/Mongo 保存后看服务端响应和重新读取的列表；「编辑」先 GET 选中对象。草稿不是落库证据；PUT 完整替换，不提供多人编辑锁。
- Redis 显示实际值、服务器 `ttl_ms` 快照与观察时间。参考倒计时只是估算，到时发起真实读取；「键不存在」与「Redis 不可用」必须区分。按「再次读取」得到新事实。
- Kafka 分开显示「生产确认」和「消费者收取」。UI 在发送前生成 ID 并写入 `#kafka?message=<UUID>`，发生错误/刷新后可用原 ID 查询，不自动重发。短时观察最多 20 秒，结束不是失败，可「手动刷新」。
- 列表读取失败时若保留上次内容，那是旧快照，不是假装最新；错误显示安全消息和可用的请求 ID。
- `/readyz.mode` 为 test/demo 时显示替身；模式未知不宣称真实连接。`production` 也不代表所有操作刚刚成功。
- 401 要重新登录；CSRF 轮换、导航、退出和旧请求响应要按会话处理，不把身份问题包装成数据库故障。

## 旧任务与 Agent 仍能学什么

可在「任务与 Agent」运行不含秘密的脚本材料，按[单 Agent 导读](AGENT_WALKTHROUGH.md)观察工具动作、最终结果和 Redis `cache_status`。`[search:销量] [stats]` 是测试控制器规则，不是 LLM 理解；三个工具只读当前任务材料。

「后台生命周期」来自 SQL；「Agent 工具动作」只显示已提交成功结果中的动作，不包含运行中/失败尝试的完整审计。架构箭头是说明，不是实时抓包；任务阶段值不是模型完成百分比。旧任务 Redis 缓存可降级，不等于直接 Redis 实验也可降级。

## 验收与安全

cookie 是 HttpOnly，写操作保留 CSRF/Origin。不要把凭据放入截图、公开日志或浏览器持久存储；Kafka URL 中只保留消息 ID，不含消息内容或认证秘密。

**新操作台须单独验收**：类型/单元/构建、真实组件、桌面/手机浏览器与本机更新是不同层级。本指南的示例不是已执行证明，本机更新仍待协调者完成云端 CI 后核验。

历史 `9c4a1908` 的 140 项后端单元/API、13 项真实集成（11+2）、30 项 UI 单元和 24 项浏览器结果仍只属于[单 Agent 验收报告](AGENT_TEST_REPORT.md)标明的提交；后续学习型 v1 `102491d2` 的结果见[开发报告](DEVELOPMENT_REPORT.md)。不将旧数字改称新操作台验收；真实 provider 全栈也不能由脚本测试推断。
