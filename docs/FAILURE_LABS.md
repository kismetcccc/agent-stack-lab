# 故障实验：先写预期，再制造故障

仅在独立开发环境使用合成任务执行。不要在真实用户数据或公网服务上做实验。默认 deterministic 模型，避免重试产生真实费用。测试完成必须恢复停止的服务。

## 证据等级

1. **单元/替身测试**：可精确控制时间与宕机窗口，验证分支和状态约束。
2. **真实 Compose 集成**：真实MySQL/Kafka/MongoDB/Redis和容器故障，验证网络及驱动。
3. **Kind smoke**：验证部署、卷、迁移与入口；不替代业务集成。
4. **真实模型验收**：需要私密凭据和显式启用，与前三者分开。

缺少Docker时，第二和第三项是“未运行/阻塞”，不是自动通过。脚本里的PASS字符串只有实际执行成功才是证据。

## 每次curl要看什么

| 操作 | 观察字段/HTTP结果 | 用普通话解释 |
|---|---|---|
| readyz | mode、dependencies | 后端是不是在连真实组件？ |
| register | 201、session cookie、csrf_token | 创建了谁的会话？不要公开这些凭据 |
| POST tasks | 202、id、status | 已接单，通常还没干完；不强求轮询捕捉每个中间态 |
| 相同请求重发 | 相同id | 点两次不应该变两张订单 |
| GET task | status、attempt_count、error | 正在做、失败重试，还是已经完成？ |
| GET results | content、model_mode、cache_status | 结果是什么？是否明确是deterministic而非真实模型？ |
| GET attempts | 尝试记录 | 为什么这项任务可能做过不止一次？ |
| logout | 204；之后受保护请求401 | 会话已经失效 |

正常路径先理解这些字段；再做断开Redis等单一故障，不必同时理解全部组件。

## 自动化真实实验入口

先在有Docker的环境启动core，再执行：

```bash
bash scripts/test-integration.sh
```

阅读[脚本](../scripts/test-integration.sh)和[集成测试](../tests/integration/test_chain.py)。脚本会停止/恢复本项目服务，不是只执行只读探针；不要与其他人在同一开发栈同时操作。正常及退出路径会尝试恢复服务；意外中断后仍应检查 `docker compose ps`。

| 实验 | 预期现象 | 不允许的现象 |
|---|---|---|
| HTTP同键同参数 | 返回原task_id | 第二条任务 |
| HTTP同键不同参数 | 409冲突 | 静默复用错误参数 |
| 相同Kafka事件重投 | Inbox去重，状态不回退 | 成功任务重新ready |
| B访问A的任务 | 详情/events/results均拒绝 | 凭UUID读取别人结果 |
| 缺失CSRF的写操作 | 拒绝 | 会话cookie自动构成完整写授权 |
| 停Redis | 任务仍可成功 | 因进度缓存丢失而丢任务 |
| 停Kafka | 提交后的任务pending，outbox保留 | 请求表面成功而任务永远失踪 |
| 恢复Kafka | 补发并最终完成 | 需要人工改数据库才能继续 |
| 停MongoDB | 不得标记无结果的成功 | SQL成功却没有持久结果 |
| 停/重建Worker | 已提交工作保留，恢复可执行 | 全部工作仅存在进程内存 |

Kafka停机时依赖readiness可能变为失败，但单纯ready标记不等同容器停止。实验应观察真实网关行为，不能假设探针失败自动拒绝所有新请求。

## 精确宕机窗口：需额外故障注入，不夸大现有脚本

以下与“启动前停Worker”不同，必须有确定性hook或受控暂停，不能用随机kill一次就声称覆盖所有窗口。当前代码已提供默认关闭的LAB_TEST_HOOKS/LAB_TEST_PAUSE_AT测试钩子（详见API契约）；钩子存在不等于对应真实故障测试已经通过。

### A. 发布后、sent_at前

relay已经收到Kafka确认，暂停后退出。重启应再次发布同event_id；Inbox约束保证只产生一次有效状态转换。说明“至少一次”为什么需要接收方幂等。

### B. Inbox提交后、offset前

消费者SQL已提交，提交offset前退出。重收消息不得再次创建执行工作；offset只允许越过已持久化的连续消息。

### C. 运行租约过期

暂停旧执行器直到lease_until，恢复器安排新attempt后再恢复旧执行器。旧fence的成功提交必须失败。单纯测试`finalize`返回false是算法测试；完整双进程竞态另需真实实验。

### D. MongoDB已保存、MySQL未成功

暂停在结果写入后。用户查询仍不得显示成功。当前跨attempt恢复可能重新调用模型，旧文档可能成为孤儿；复用和清理是后续专项，不把“结果ID稳定”误读为已消除全部重复调用。

### E. 暂时/永久失败与DLQ

用受控适配器制造超时、永久拒绝、超出尝试次数。观察next_attempt_at、attempt_count与终态失败outbox；真实Kafka上的死信记录另行读取验收。教学记录应区分“失败事件已排入outbox”和“Kafka已确认接收DLQ”。

## 实验记录模板

- commit、时间、环境与实际命令；
- 模型模式、真实依赖/替身；
- 故障注入点、注入前任务状态；
- 观察到的task_id/event_id（只使用合成数据）；
- 恢复步骤、最终状态、重复事件/尝试数；
- 通过/失败/未运行，以及日志和测试报告位置；
- 是否恢复全部服务，有无遗留数据或孤儿结果。

禁止记录密码、session cookie、CSRF token、模型key和真实私人prompt。`docker compose config`可能展开秘密，不把完整输出上传到公开CI附件。

## curl 后端闭环（Bash / WSL2，无需前端）

前提：真实core已启动，安装curl与Python3。以下使用一次性合成帐号；密码和cookie写入权限受限的临时目录，不提交仓库。命令目前按真实接口代码核对，未在缺少Docker的当前云端冒充已执行成功。

```bash
set -euo pipefail
BASE=http://localhost:8080
TMP_LAB=$(mktemp -d)
chmod 700 "$TMP_LAB"
trap 'rm -rf "$TMP_LAB"' EXIT
python - "$TMP_LAB/register.json" <<'PY'
import json, secrets, sys
with open(sys.argv[1], 'w') as f:
    json.dump({'username': 'lab_' + secrets.token_hex(6),
               'password': secrets.token_urlsafe(24)}, f)
PY
# 1. readyz应显示真实mysql/mongo/kafka；demo不算真实集成。
curl -fsS "$BASE/readyz"
# 2. 注册并保存会话；响应中的csrf_token用于后续写操作。
curl -fsS -c "$TMP_LAB/cookies" -H 'Content-Type: application/json' \
  --data-binary @"$TMP_LAB/register.json" \
  "$BASE/api/v1/auth/register" > "$TMP_LAB/auth.json"
CSRF=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["csrf_token"])' "$TMP_LAB/auth.json")
KEY=$(python -c 'import uuid; print(uuid.uuid4())')
printf '%s' '{"prompt":"解释 MySQL Outbox 如何避免数据库写入与消息发布脱节"}' > "$TMP_LAB/task.json"
# 3. 提交返回202，只表示接受，不是执行完成。
curl -fsS -b "$TMP_LAB/cookies" -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -H "Idempotency-Key: $KEY" \
  --data-binary @"$TMP_LAB/task.json" "$BASE/api/v1/tasks" > "$TMP_LAB/task-response.json"
TASK_ID=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$TMP_LAB/task-response.json")
# 4. 原样重发必须得到相同task_id。
curl -fsS -b "$TMP_LAB/cookies" -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -H "Idempotency-Key: $KEY" \
  --data-binary @"$TMP_LAB/task.json" "$BASE/api/v1/tasks" > "$TMP_LAB/repeated.json"
python - "$TMP_LAB/task-response.json" "$TMP_LAB/repeated.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['id'] == json.load(open(sys.argv[2]))['id']
print('same-key request returned the same task')
PY
# 5. 轮询最多90秒：超时是实验失败/待诊断，不是假成功。
STATUS=pending
for i in $(seq 1 90); do
  curl -fsS -b "$TMP_LAB/cookies" "$BASE/api/v1/tasks/$TASK_ID" > "$TMP_LAB/current.json"
  STATUS=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$TMP_LAB/current.json")
  printf '%s\n' "$STATUS"
  if [ "$STATUS" = succeeded ] || [ "$STATUS" = failed ]; then break; fi
  sleep 1
done
[ "$STATUS" = succeeded ] || { echo 'Task did not succeed; inspect task and attempts'; exit 1; }
# 6. 读取结果和安全事件，deterministic标签必须可见。
curl -fsS -b "$TMP_LAB/cookies" "$BASE/api/v1/tasks/$TASK_ID/results"
# 再读一次观察cache_status：缓存可用且未过期时应hit。
curl -fsS -b "$TMP_LAB/cookies" "$BASE/api/v1/tasks/$TASK_ID/results"
curl -fsS -b "$TMP_LAB/cookies" "$BASE/api/v1/tasks/$TASK_ID/events"
curl -fsS -b "$TMP_LAB/cookies" "$BASE/api/v1/tasks/$TASK_ID/attempts"
# 7. 退出让会话失效；trap删除本地临时凭据。
curl -fsS -b "$TMP_LAB/cookies" -H "X-CSRF-Token: $CSRF" \
  -X POST "$BASE/api/v1/auth/logout"
```

接着用自动化故障脚本完成停止Redis、Kafka、MongoDB和Worker的实验。先观察每个阶段，再看 `service.py` 中对应事务；不要在上面的成功链路中随意加入停库命令导致剩余清理和恢复被跳过。

若重复执行要使用新的合成帐号；若调用`/auth/me`轮换CSRF后再写入，应使用其返回的新token，不能继续使用旧变量。生产密钥不应照此以命令行header展示；这里仅是独立本地教学会话。
