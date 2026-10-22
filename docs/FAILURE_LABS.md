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
| 停MySQL | `/healthz`仍200，`/readyz`为503；已登录的提交/列表/详情/结果/工具步骤均503 | 伪造202接单，或用Redis缓存绕过SQL会话/所有权检查 |
| 恢复MySQL，再恢复Worker | 原任务、结果引用、幂等键与所有权保留；原pending/outbox继续完成 | 重启后丢任务、需要重置数据库，或陌生帐号读到缓存结果 |
| 停Redis | 任务仍可成功 | 因进度缓存丢失而丢任务 |
| 停Kafka | 提交后的任务pending，outbox保留 | 请求表面成功而任务永远失踪 |
| 恢复Kafka | 补发并最终完成 | 需要人工改数据库才能继续 |
| 停MongoDB | 不得标记无结果的成功 | SQL成功却没有持久结果 |
| 停/重建Worker | 已提交工作保留，恢复可执行 | 全部工作仅存在进程内存 |

Kafka停机时依赖readiness可能变为失败，但单纯ready标记不等同容器停止。实验应观察真实网关行为，不能假设探针失败自动拒绝所有新请求。

## MySQL真实停机与恢复：权威账本不能由缓存替代

**当前证据状态：新增探针与离线辅助函数测试已实现，真实Docker停库实验待对应提交的CI验收。** 缺少Docker的云端不能运行本实验。基线的13项真实集成测试和Redis/Kafka/MongoDB/Worker故障证据不能代替这里新增的MySQL停机证据；最新执行结果以[当前任务清单](DEVELOPMENT_PLAN.md)和CI报告为准。

入口仍是 `bash scripts/test-integration.sh`，探针实现见 [outage_probe.py](../tests/integration/outage_probe.py)。新增实验不改生产逻辑、不重启API、不删除数据库或卷，也不调用真实模型。它先从真实 `/readyz` 验证 `production` 适配器与 `deterministic` 模型；`production` 在这里不代表已达到生产安全标准。

### 五个阶段及可检查的证据

| 阶段/命令 | 实际动作和必须成立的断言 |
|---|---|
| `mysql-prepare` | 创建两个一次性合成帐号A/B；A的基线任务成功，SQL提交结果引用；结果读取明确出现Redis `hit`；B不能读A的任一任务子资源 |
| 停Worker → `mysql-enqueue` | A提交第二个任务得到真实202；直接查询MySQL确认 `pending`、零attempt、无result_id、唯一未发outbox；记住原task/outbox ID |
| 停MySQL → `mysql-unavailable` | 实际等待 `/readyz` 返回503且mysql为down、mongo/kafka仍up；`/healthz`仍200；已存在会话的创建、列表、待执行任务详情、成功任务结果/工具步骤返回503 `database_unavailable`，不是客户端超时伪装成503。分别用A/B请求缓存结果，并在前后直接确认Redis key仍存在，排除“缓存已经过期所以看似没有越权”的假通过 |
| 启MySQL → `mysql-restored` | 有界轮询真实 `/readyz` 到200；此时Worker仍停。原pending与未发outbox不变，基线成功状态/attempt数/result_id及结果摘要不变；停库时503的创建没有写入任务；重发原幂等键仍是同一个pending任务；A可读、B的详情/events/attempts/results/agent-steps均404且列表为空 |
| 启Worker → `mysql-complete` | 有界等待原pending任务成功；原outbox的sent_at与对应inbox均存在，SQL结果引用和可读Mongo结果/最终步骤成立；先前成功任务没有重新执行；再次验证所有权和readiness |

探针使用45秒单次HTTP超时，容纳停容器后DNS/SQL连接失败可能持续约20秒的情况；readiness恢复轮询最多180秒、停库观测最多120秒、任务成功轮询最多180秒。超时是失败，不制造HTTP响应或补写成功状态；不靠固定等待几秒猜测MySQL是否启动。这里验证的是**先停Worker、已接受pending工作跨MySQL重启后可继续**，不是运行中的执行器突然断库或精确宕机窗口验收。

### 单独复现实验（仅独立、已启动的合成数据core）

通常直接运行完整脚本即可；以下只用于逐阶段学习。执行时不可并行运行另一份集成/宕机脚本，它们共用私有状态文件和同一个Worker。先在项目根目录启动core并构建API镜像；以下不初始化或覆盖现有 `.env`。

```bash
(
  set -euo pipefail
  DC=(docker compose -f compose.yaml -f compose.test.yaml)
  probe() { "${DC[@]}" run --rm --no-deps --entrypoint python integration /tests/integration/outage_probe.py "$1"; }
  cleanup_mysql_lab() {
    rc=$?
    rm -f test-results/outage-state.json
    # 先恢复实际依赖健康，再恢复Worker；不删除卷。
    if docker compose up -d --no-deps --wait --wait-timeout 180 mysql redis mongo kafka; then
      docker compose up -d --no-deps --force-recreate --wait --wait-timeout 180 worker || rc=1
    else
      echo '依赖恢复失败；检查 docker compose ps 后再启动Worker' >&2
      rc=1
    fi
    exit "$rc"
  }
  trap cleanup_mysql_lab EXIT
  mkdir -p test-results
  chmod 777 test-results # 仅此隔离实验目录，允许非root测试容器写报告
  "${DC[@]}" build integration
  probe mysql-prepare
  docker compose stop worker
  probe mysql-enqueue
  docker compose stop mysql
  probe mysql-unavailable
  docker compose start mysql
  probe mysql-restored
  docker compose start worker
  probe mysql-complete
)
docker compose ps
```

正常或失败退出都会尝试依次恢复MySQL/Redis/MongoDB/Kafka和Worker，并核验健康；恢复失败会使脚本非零退出，不把 `|| true` 当成功。终端被强制杀死或runner中止时trap不保证执行，须检查服务状态并按同样顺序恢复。本实验不执行 `down --volumes`、删库、重置消费组或清缓存。CI最后销毁独立runner的临时卷属于隔离环境清理，不是业务恢复步骤。

### 证据计数与隐私

- 原有 `integration.xml`、`recovery.xml` 仍是**合计13项pytest真实集成测试**，没有把新增脚本断言塞进该数量。
- `mysql-outage.xml` 另记**1个真实Compose编排场景、5个阶段**，标明“NOT a pytest test”；全部阶段成功才算通过。中间状态记录为未完成/跳过，失败则记录失败类型和已通过阶段。CI日志同时打印每阶段 `PASS`；只看命令文本或未运行时的文件不算实测证据。
- [test_mysql_outage_probe.py](../backend/tests/test_mysql_outage_probe.py) 是离线**单元测试**：用 `httpx.MockTransport` 验证探针拒绝假成功、错误状态/模式、超时冒充503、顺序错误及敏感错误输出；用隔离命令替身检查shell成功/失败路径和恢复顺序。它们不连接MySQL、不启动Docker，也不能替代容器故障验收。
- 会话、CSRF、合成幂等键仅放在 `test-results/outage-state.json`（0600；拒绝符号链接）；成功或退出清理时删除。该文件不得上传附件，现有CI排除规则继续保留。可公开的JUnit只含静态阶段名、测试类型与成功/失败信息，不记录cookie、key、连接串、原始响应或原始驱动异常。

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

接着用自动化故障脚本完成停止MySQL、Redis、Kafka、MongoDB和Worker的实验。先观察每个阶段，再看 `service.py` 中对应事务；不要在上面的成功链路中随意加入停库命令导致剩余清理和恢复被跳过。

若重复执行要使用新的合成帐号；若调用`/auth/me`轮换CSRF后再写入，应使用其返回的新token，不能继续使用旧变量。生产密钥不应照此以命令行header展示；这里仅是独立本地教学会话。
