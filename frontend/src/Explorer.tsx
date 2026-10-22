import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  Code2,
  Database,
  GitBranch,
  Layers,
  Server,
  Workflow,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
export const roles = [
  {
    id: "api",
    name: "API",
    subtitle: "把请求变成可靠的任务",
    icon: Server,
    problem:
      "给浏览器一个明确、安全的入口。先确认你是谁，再校验输入，把任务和待发送事件一起保存。",
    not: "不在 HTTP 请求中执行耗时模型；返回 202 不代表任务已完成。",
    input: "带会话、CSRF Token 和幂等键的 POST /api/v1/tasks",
    output: "任务 ID、初始状态 pending；同一事务中的 Outbox 记录。",
    failure: "未提交的事务回滚。响应丢失时，用相同幂等键重试会取回原任务。",
    source: "backend/app.py · backend/auth.py · backend/service.py",
    experiment: "用两个并发请求提交相同内容与幂等键，确认只创建一个任务。",
    key: "api",
  },
  {
    id: "mysql",
    name: "MySQL",
    subtitle: "记录任务的事实",
    icon: Database,
    problem:
      "用事务保存用户、任务状态和执行尝试。无论缓存或进程发生什么，系统都能回来查询和恢复工作。",
    not: "不保存大段报告正文，不承担消息广播；缓存与消息队列不能替代它裁决状态。",
    input: "API 的任务事务；Worker 的领取、状态更新与结果引用。",
    output: "权威任务状态、持久化生命周期事件、当前执行租约。",
    failure: "关键依赖。数据库不可用时不能可靠受理、领取或提交任务。",
    source: "backend/db.py · backend/service.py · backend/migrate.py",
    experiment: "并发重复创建、过期租约恢复、旧 fencing token 提交被拒。",
    key: "mysql",
  },
  {
    id: "kafka",
    name: "Kafka",
    subtitle: "把工作交给后台",
    icon: GitBranch,
    problem:
      "让 API 与执行器不必同时在线。Relay 将已经持久化的事件发往 Kafka，Consumer 收到后先写入 Inbox，再确认消费。",
    not: "不是任务状态数据库；至少一次交付不等于整个系统恰好执行一次。",
    input: "Outbox 中带 event_id、task_id、trace_id 的任务事件。",
    output: "Consumer 可重放的消息；同一 task_id 进入同一分区。",
    failure: "Kafka 停机时任务仍可受理，但停留 pending；恢复后 Outbox 补发。",
    source: "backend/adapters.py · backend/worker.py",
    experiment:
      "停用 Kafka 后提交任务，再恢复，观察 outbox_sent 与 ready 事件。",
    key: "kafka",
  },
  {
    id: "worker",
    name: "Worker",
    subtitle: "执行任务，也负责恢复",
    icon: Workflow,
    problem:
      "在 HTTP 请求之外领取任务。单 Agent 控制器根据当前观察选择只读工具或结束：决策 → 校验预算 → 工具结果 → 再次决策。Worker 仍是执行器，不是多个 Agent；有限重试和租约恢复仍由后台负责。",
    not: "不是新的事实来源；模型调用不放在数据库长事务里，也不承诺外部模型只计费一次。",
    input: "已持久化为 ready 的任务与新的执行租约。",
    output: "MongoDB 结果文档、MySQL 成功状态及结果引用。",
    failure:
      "退出后由租约恢复；旧执行器无法用过期 token 覆盖新的结果。首版仅支持单 Worker 副本。",
    source: "backend/worker.py · backend/domain.py · backend/service.py",
    experiment:
      "领取后停止执行器，等待租约到期，观察新 attempt 和 fencing token。",
    key: "worker",
  },
  {
    id: "mongo",
    name: "MongoDB",
    subtitle: "保存灵活的结果文档",
    icon: Database,
    problem:
      "报告和工具摘要不像任务表那样固定。文档存储容纳这些结构变化，并用稳定的 attempt 专属 ID 保存不可变结果。",
    not: "不和 MySQL 构成跨库原子事务；不能自行把任务判定为成功。",
    input: "本次 attempt 生成的结果文档。",
    output: "稳定 result_id，随后由 MySQL 提交成功状态和引用。",
    failure:
      "写入失败不能标记任务成功。写入后宕机可能留下孤儿文档，当前未做自动清理。",
    source: "backend/adapters.py · backend/service.py",
    experiment: "让 Mongo 写失败，确认没有虚假 succeeded；恢复后检查新尝试。",
    key: "mongo",
  },
  {
    id: "redis",
    name: "Redis",
    subtitle: "加速查询，而不改变事实",
    icon: Database,
    problem:
      "缓存已完成任务的不可变报告，减轻文档库查询。先通过 SQL 验证所有权和结果引用，再访问缓存，TTL 为 300 秒。",
    not: "不是任务状态或权限的唯一来源；停机或清空不能丢失任务。",
    input: "已授权的不可变 result_id。",
    output: "cache_status：hit / miss / unavailable / disabled，以及报告内容。",
    failure: "缓存失效时回源 MongoDB。就绪接口未探测 Redis，不能据此宣称在线。",
    source: "backend/adapters.py · backend/app.py",
    experiment:
      "连续读取结果观察命中；停用 Redis 后报告应仍可读取，状态为 unavailable。",
    key: "redis",
  },
];
export type Role = (typeof roles)[number];
export function Explorer({
  roleId,
  onRole,
  health,
}: {
  roleId: string;
  onRole: (id: string) => void;
  health: Record<string, unknown> | null;
}) {
  const [route, setRoute] = useState<"submit" | "read">("submit");
  const detailHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (
      roles.some((item) => item.id === roleId) &&
      window.matchMedia?.("(max-width: 900px)").matches
    ) {
      detailHeading.current?.scrollIntoView({ block: "start" });
      detailHeading.current?.focus({ preventScroll: true });
    }
  }, [roleId]);
  const [advanced, setAdvanced] = useState(false);
  const role = roles.find((r) => r.id === roleId) || roles[0];
  const deps = health?.dependencies as Record<string, string> | undefined;
  const raw = deps?.[role.key];
  const state =
    raw === "up"
      ? "就绪检查通过"
      : raw === "down"
        ? "就绪检查失败"
        : raw === "in_memory_test_adapter"
          ? "内存测试适配器"
          : role.id === "mysql" && deps?.sqlite
            ? "SQLite 替代 · 非 MySQL"
            : "未提供实时探针 / 通过任务观察";
  const node = (id: string, n: string) => {
    const r = roles.find((r) => r.id === id)!;
    const Icon = r.icon;
    return (
      <button
        key={id}
        className={`chain-node ${role.id === id ? "chosen" : ""}`}
        onClick={() => onRole(id)}
        aria-pressed={role.id === id}
      >
        <span className="node-order">{n}</span>
        <Icon size={21} />
        <strong>{r.name}</strong>
        <small>{r.subtitle}</small>
        <ChevronRight size={14} />
      </button>
    );
  };
  return (
    <div className="explorer-layout">
      <section className="explorer-main">
        <div className="intro-kicker">一个任务，六个角色</div>
        <h1>把后端，看清楚。</h1>
        <p className="intro-text">
          先理解每个组件为什么存在，再沿着一条真实任务，
          <br className="desktop-break" />
          观察数据如何保存、传递与恢复。
        </p>
        <div className="route-tabs" role="tablist" aria-label="请求链路">
          <button
            role="tab"
            aria-selected={route === "submit"}
            onClick={() => setRoute("submit")}
          >
            提交与执行 <span>异步</span>
          </button>
          <button
            role="tab"
            aria-selected={route === "read"}
            onClick={() => setRoute("read")}
          >
            查询与结果 <span>同步</span>
          </button>
        </div>
        <div className="journey">
          <div className="journey-label">
            <span className="small-circle" />
            浏览器发起{route === "submit" ? "任务" : "查询"}
            <code>
              {route === "submit"
                ? "POST /api/v1/tasks"
                : "GET /api/v1/tasks/:id/results"}
            </code>
          </div>
          {route === "submit" ? (
            <>
              <div className="chain-row">
                {node("api", "01")}
                <ArrowRight className="chain-arrow" size={18} />
                {node("mysql", "02")}
              </div>
              <div className="return-line">
                <span>↑ 返回任务 ID · 202 Accepted</span>
                <span>这里表示已受理，不是已完成</span>
              </div>
              <div className="async-divider">
                <span>后台异步执行</span>
                <ArrowDown size={15} />
              </div>
              <div className="chain-row">
                {node("kafka", "03")}
                <ArrowRight className="chain-arrow" size={18} />
                {node("worker", "04")}
              </div>
              <div className="chain-connector">
                <ArrowDown size={16} />
                <span>保存结果，然后提交成功状态</span>
              </div>
              <div className="chain-row">
                {node("mongo", "05")}
                <ArrowRight className="chain-arrow" size={18} />
                <button className="commit-node" onClick={() => onRole("mysql")}>
                  <Database size={18} />
                  <div>
                    <strong>MySQL 提交引用</strong>
                    <small>此时，任务才真正成功</small>
                  </div>
                </button>
              </div>
              <div className="cache-note">
                <button onClick={() => onRole("redis")}>
                  <Database size={16} />
                  <strong>Redis</strong>
                  <span>查询时的可丢弃加速层</span>
                  <ArrowUpRight size={14} />
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="chain-row">
                {node("api", "01")}
                <ArrowRight className="chain-arrow" size={18} />
                {node("mysql", "02")}
              </div>
              <div className="chain-connector">
                <ArrowDown size={16} />
                <span>先校验所有权，再读取已提交的结果引用</span>
              </div>
              <div className="chain-row query-branch">
                {node("redis", "03")}
                <div className="cache-fallback-arrow">
                  <span>miss / unavailable / disabled</span>
                  <ArrowRight size={18} />
                  <small>回源</small>
                </div>
                {node("mongo", "04")}
              </div>
              <div className="cache-hit-branch">
                ↳ hit → 直接返回报告，不读取 MongoDB
              </div>
              <div className="return-line">
                <span>命中缓存直接返回；未命中或失效则回源</span>
              </div>
              <p className="read-explanation">
                任务状态始终从 SQL
                读取。报告只有在任务成功、结果引用已提交后才可读取；Redis
                不参与权限裁决。
              </p>
            </>
          )}
        </div>
        <button
          className="advanced-toggle"
          aria-expanded={advanced}
          onClick={() => setAdvanced(!advanced)}
        >
          <Code2 size={15} />
          {advanced ? "收起" : "展开"}可靠性细节：Outbox、Inbox 与租约
          <ChevronRight size={14} />
        </button>
        {advanced && (
          <div className="advanced-content">
            <p>
              <strong>Outbox：</strong>任务与事件同一事务提交，relay
              可恢复地发布。确认后未标记会重复发送，因此不能假设消息只到一次。
            </p>
            <p>
              <strong>Inbox：</strong>先用唯一事件 ID 去重并落库，再提交 Kafka
              offset，避免重复工作或提前确认。
            </p>
            <p>
              <strong>租约与 fencing：</strong>每次执行领取新
              token。恢复器接手过期任务，旧执行器无法覆盖新结果。
            </p>
          </div>
        )}
        <div className="deployment-note">
          <Layers size={17} />
          <div>
            <strong>部署层 · 留到下一步</strong>
            <p>
              Kubernetes
              管理这些进程，不是业务请求链路的一跳。当前页面不表示集群已经部署或验收。
            </p>
          </div>
        </div>
        <div className="start-learning">
          <BookOpen size={17} />
          <span>理解了职责？提交一个任务，看看真实事件。</span>
          <a href="#lab">
            运行任务 <ArrowRight size={14} />
          </a>
        </div>
      </section>
      <aside
        className="inspector"
        aria-label="组件详情"
        data-testid="component-detail"
      >
        <div className="inspector-label">
          组件说明 <span>选中节点查看</span>
        </div>
        <div className="inspector-title">
          <role.icon size={25} />
          <div>
            <h2 ref={detailHeading} tabIndex={-1}>
              {role.name}
            </h2>
            <p>{role.subtitle}</p>
          </div>
        </div>
        <div
          className={`dependency-state ${raw === "down" ? "down" : raw === "up" ? "up" : ""}`}
        >
          <span />
          {state}
        </div>
        <section>
          <h3>解决什么问题</h3>
          <p>{role.problem}</p>
        </section>
        <section>
          <h3>不负责什么</h3>
          <p>{role.not}</p>
        </section>
        <section className="io-block">
          <h3>输入 → 输出</h3>
          <dl>
            <dt>IN</dt>
            <dd>{role.input}</dd>
            <dt>OUT</dt>
            <dd>{role.output}</dd>
          </dl>
        </section>
        <section>
          <h3>失败会怎样</h3>
          <p>{role.failure}</p>
        </section>
        <section>
          <h3>对应源码</h3>
          <code>{role.source}</code>
        </section>
        <details className="inspector-experiment">
          <summary>
            <span>动手验证</span>
            <ChevronRight size={14} />
          </summary>
          <p>{role.experiment}</p>
          <code>docs/FAILURE_LABS.md</code>
          <small>说明不是执行结果。请在隔离开发环境按文档操作。</small>
        </details>
      </aside>
    </div>
  );
}
