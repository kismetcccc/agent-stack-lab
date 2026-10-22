import {
  ArrowRight,
  Database,
  FileJson2,
  KeyRound,
  RefreshCw,
  Send,
} from "lucide-react";
export const playgrounds = [
  {
    id: "mysql",
    name: "MySQL",
    label: "MySQL 记录",
    purpose: "创建、读取、更新和删除教学记录。",
    action: "打开记录",
    icon: Database,
    evidence: "服务端 ID、内容和更新时间",
  },
  {
    id: "mongo",
    name: "MongoDB",
    label: "MongoDB 文档",
    purpose: "保存 JSON 文档，查看与完整替换。",
    action: "打开文档",
    icon: FileJson2,
    evidence: "持久化文档及服务端生成的 ID",
  },
  {
    id: "redis",
    name: "Redis",
    label: "Redis 键值",
    purpose: "按键读取真实值与 TTL 快照。",
    action: "打开键值",
    icon: KeyRound,
    evidence: "真实值、TTL 与服务端观察时间",
  },
  {
    id: "kafka",
    name: "Kafka",
    label: "Kafka 消息",
    purpose: "查看消息历史，分别核对生产与消费。",
    action: "打开消息",
    icon: Send,
    evidence: "生产确认与消费者回执",
  },
];
export type Health = {
  mode?: string;
  model_mode?: string;
  status?: string;
  dependencies?: Record<string, unknown>;
  [key: string]: unknown;
};
export type Readiness = {
  data: Health | null;
  receivedAt: string | null;
  httpStatus: number | null;
  loading: boolean;
  error: string;
  stale: boolean;
};
export function probeLabel(health: Health | null, component: string) {
  if (component === "redis") return "未提供总体探针";
  const dependencies = health?.dependencies;
  if (component === "mysql" && dependencies?.sqlite !== undefined)
    return "SQLite 替代 · 非 MySQL";
  const value = dependencies?.[component];
  if (value === "in_memory_test_adapter") return "测试替身";
  if (value === "up") return "探测通过";
  if (value === "down") return "未就绪";
  return "未知 / 未取得";
}
export default function PlaygroundHome({
  readiness,
  onRefresh,
}: {
  readiness: Readiness;
  onRefresh: () => void;
}) {
  const { data, receivedAt, httpStatus, loading, error, stale } = readiness;
  const mode =
    data?.mode === "production"
      ? "真实组件适配器（production）"
      : data?.mode
        ? `${data.mode} · 测试 / 离线模式`
        : "运行模式未知";
  return (
    <section className="console-overview">
      <div className="console-page-heading">
        <div>
          <h1>总览</h1>
          <p>本地资源与现有接口证据。选择组件，直接开始操作。</p>
        </div>
        <span className="console-tag">本地共享</span>
      </div>
      <section className="console-surface">
        <div className="console-toolbar">
          <h2>本地资源</h2>
          <button disabled={loading} onClick={onRefresh}>
            <RefreshCw size={15} />
            {loading ? "检查中…" : "刷新检查"}
          </button>
        </div>
        <div className="console-table-scroll">
          <table className="console-table" aria-label="本地资源">
            <thead>
              <tr>
                <th>组件</th>
                <th>用途</th>
                <th>探测结果 / 证据</th>
                <th>入口</th>
              </tr>
            </thead>
            <tbody>
              {playgrounds.map(({ id, name, purpose, action, icon: Icon }) => (
                <tr key={id} data-testid={`resource-${id}`}>
                  <th scope="row">
                    <span className="console-resource-name">
                      <Icon size={18} />
                      {name}
                    </span>
                  </th>
                  <td>{purpose}</td>
                  <td>
                    <span
                      className={`console-probe ${stale ? "stale" : data?.dependencies?.[id] === "down" ? "down" : ""}`}
                    >
                      {probeLabel(data, id)}
                    </span>
                    <small>
                      {id === "redis"
                        ? "进入键值页验证"
                        : id === "kafka"
                          ? "ping 不代表消费者已收取消息"
                          : "仅代表本次探测"}
                    </small>
                  </td>
                  <td>
                    <a className="console-link" href={`#${id}`}>
                      {action}
                      <ArrowRight size={14} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div
          className="console-readiness"
          data-testid="readiness-summary"
          aria-live="polite"
        >
          <p>
            <strong>
              {stale
                ? "上次检查，非当前状态"
                : loading && !data
                  ? "正在读取 /readyz"
                  : data
                    ? "最近检查"
                    : "状态未知 / 未取得"}
            </strong>
            {receivedAt &&
              ` · ${new Date(receivedAt).toLocaleString("zh-CN", { hour12: false })}（浏览器收取响应时间）`}
            {httpStatus !== null && ` · HTTP ${httpStatus}`}
          </p>
          {error && (
            <p className="console-warning" role="status">
              {error}
            </p>
          )}
          <p>
            后端：{mode}。API 可响应不等于 Worker 正在工作；本页不提供 Worker
            活跃或主机资源探针。
          </p>
          <details>
            <summary>检查详情</summary>
            <pre>
              {data
                ? JSON.stringify(data, null, 2)
                : "尚未取得有效的检查响应。"}
            </pre>
          </details>
        </div>
      </section>
      <section className="console-overview-notes">
        <div>
          <h2>共享教学空间</h2>
          <p>
            四组件教学数据不按帐号隔离；任务仍属于当前帐号。请勿写入隐私、密钥或重要资料。
          </p>
        </div>
        <div>
          <h2>继续学习</h2>
          <p>
            <a href="#overview">架构说明</a>
            <a href="#learn">学习路径</a>
            <a href="#experiments">故障实验</a>
          </p>
        </div>
      </section>
    </section>
  );
}
