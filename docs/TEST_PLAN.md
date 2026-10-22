# 后端真实链路验收计划与证据

## 当前范围与状态（2026-10-22）

用户最新指示：**先理清并验收后端**。浏览器 UI 和 Kubernetes 当前延期；已有草稿保留，不作为本轮完成条件，也不宣称已通过。

状态词：**已通过** = 实际执行且退出成功；**失败** = 实际断言不符；**未运行** = 尚无执行证据；**环境阻塞** = 缺少运行前提。测试代码存在或 collection 成功都不等于真实链路通过。

| 类别 | 当前证据 | 状态 |
|---|---|---|
| 集成测试导入/收集 | `.venv/bin/python -m pytest tests/integration --collect-only -q`，9 项成功收集 | 已通过（仅收集） |
| Python 语法 / shell 语法 | `python -m compileall` / `bash -n scripts/test-integration.sh` | 已通过（仅语法） |
| MySQL/Kafka/MongoDB/Redis 真集成 | 云端没有 Docker 二进制，不启用 SQLite 或 memory 替代 | 环境阻塞 / 未运行 |
| Compose 停机恢复与日志扫描 | 需要实际 Docker 服务 | 未运行 |
| 浏览器桌面/移动端 | `tests/e2e` 草稿保留；依赖/浏览器未验收，最新范围延期 | 未运行 / 延期 |
| Kind 部署与业务链路 | 由基础设施脚本负责，最新范围延期 | 未运行 / 延期 |
| live 模型 | 等待用户安全配置供应商 API，不在公开文件填密钥 | 未运行 |

## 执行方式

仅在隔离开发/CI环境运行。脚本会暂停 Redis、Kafka、MongoDB、Worker，并创建临时教学帐号/任务；不在共享生产环境运行。

```bash
python scripts/infra-init-env.py
# 构建镜像并启动 core，依据 infra 指南等待所有核心服务就绪
# 下列脚本要求 core 已经运行
bash scripts/test-integration.sh
```

测试 runner 继承 production API 的真实连接配置，使用 `http://api:8000`，不暴露数据库端口。`DATABASE_URL` 必须为 MySQL；`LAB_MODE` 必须为 `production`；显式验证 SQL版本、Mongo ping、Redis ping，并实际读写 Kafka。缺少配置、服务不可用或断言失败均以非零退出，**不 skip、不自动降级**。唯一替身是 deterministic / 注入故障的模型适配器。

报告目录：`test-results/integration.xml`、`test-results/recovery.xml`；故障脚本逐阶段失败即终止，CI 控制台保留明确断言。不输出 `.env`、连接串、Cookie 或密码。临时故障状态包含测试会话，权限 0600，退出 trap 删除；不要上传它。正常停止不删除数据卷。

## 覆盖与断言

1. **完整链路**：注册 → HttpOnly session → logout/login → 创建任务 → 最终 HTTP success；实际查询 MySQL task/outbox sent/inbox/attempt 与 fencing；独立 Kafka consumer 从真实 topic 找到 event_id；Mongo `_id` 必须等于 SQL 已提交 result_id；results/events API 必须可读；model_mode 明确 deterministic。
2. **Redis 权威边界**：真实 TTL progress 写入存在；结果缓存按 result_id 验证首次 miss、后续 hit 与 TTL；删除缓存后任务 SQL/API 仍成功；停止 Redis 后新任务依旧成功。
3. **HTTP 并发幂等**：同帐号同键同内容 8 并发请求只产生一个任务；不同内容同键返回409；两个不同内容并发竞争一成功一冲突；大小写不同的幂等键必须分别创建，防止MySQL collation混淆。
4. **消息重复**：真实 Kafka producer 重发同 event_id，实际等待 consumer 后 inbox/attempt 数量仍为1。
5. **崩溃窗口**：停 Worker 后在真实 Kafka 发送、保留 outbox 未标记，再 relay 重发；直接调用生产 receive 在真实 MySQL 事务写 inbox 并重放，验证幂等。**这是边界注入，不是杀进程精确卡在 ACK 指令处；精确SIGKILL脚本正在单独准备，未加入本轮CI/发布、未运行。**
6. **租约/fencing**：真实 SQL 写过期租约，恢复为持久 retry_wait，再推进到期重领；旧 fence 在新尝试之前/之后均拒绝提交；旧 Mongo 孤儿文档不能成为 SQL正式结果。
7. **有限重试/DLQ**：仅模型注入暂时故障；每次 next_attempt_at 持久化且将来到期；达到 MAX_ATTEMPTS 后 task failed，无 result引用，唯一 task.failed outbox，并在真实 Kafka DLQ 观察到该 event_id。
8. **依赖停机**：Kafka停止时 HTTP202 + SQLpending，无虚假成功，恢复后完成；Mongo停止时不能 SQL成功，恢复后完成；对已完成结果清除 Redis 缓存后停 Mongo，读取503而不是虚构结果，SQL状态不变、healthz200、readyz503；Worker停止后入队，替换进程后完成。
9. **身份/授权**：匿名列表/创建/详情/events/results401；跨用户资源403/404；缺失/旧CSRF403；恶意Origin403；会话轮换/过期/退出；分页边界、空白prompt和过长输入422；真实无Content-Length的chunked >64KiB正文413；404/405和malformed JSON统一错误格式；SQL只保存 session/CSRF 摘要。
10. **敏感信息**：DTO 禁止密码哈希/会话摘要/连接串/堆栈字段；API+Worker日志在内存中检测已知测试凭据、环境密钥、Bearer/Cookie/DSN 模式。不输出原日志，该扫描不等于通用安全证明。

## 必须诚实保留的限制

- 核心测试未执行前，不得称为“后端全链路验收通过”。CI 执行结果及 commit/run URL 是最终依据。
- 精确SIGKILL增强已从主脚本分离（scripts/test-crash-windows.sh / compose.fault-test.yaml），暂不发布/执行；需按task_id过滤暂停点避免旧消息误触发。现有 SQL租约注入和停止后入队重启覆盖不同边界，不能混称。
- 多 relay、多个 executor 的长时竞争/吞吐、真实模型网络响应丢失/计费、长期负载、备份恢复均未验收。
- 没有测量性能或容量；不写虚构的吞吐、延迟、内存或最低硬件数据。
- 跨 MySQL/Kafka/Mongo/模型没有共同事务；只验证显式实现的至少一次交付及幂等，不宣称端到端 exactly-once。
