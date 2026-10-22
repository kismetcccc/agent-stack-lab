import { useEffect, useRef, useState, type FormEvent } from "react";
import { RefreshCw, Send } from "lucide-react";
import { ApiError, message, request } from "./api";
import { type KafkaMessage, type LabProps, labTime } from "./lab";
import ConsoleDrawer from "./ConsoleDrawer";
import { commitHash, useNavigationGuard } from "./navigation";
import {
  Empty,
  JsonView,
  LabError,
  ListTools,
  Pagination,
  useLabList,
  useLabOperation,
} from "./LabShared";

const readSelected = () =>
  location.hash.split("?")[0] === "#kafka"
    ? new URLSearchParams(location.hash.split("?")[1]).get("message")
    : null;

export default function KafkaLab(props: LabProps) {
  const operation = useLabOperation(props),
    list = useLabList<KafkaMessage>(
      "/lab/kafka/messages",
      props.onUnauthorized,
    ),
    requestLeave = useNavigationGuard();
  const [composer, setComposer] = useState(false),
    [key, setKey] = useState(""),
    [value, setValue] = useState(""),
    [newMessageWarning, setNewMessageWarning] = useState(false);
  const [attempt, setAttempt] = useState<string | null>(null),
    attemptLock = useRef<string | null>(null);
  const [selected, setSelected] = useState(readSelected),
    selectedRef = useRef(selected);
  selectedRef.current = selected;
  const [detail, setDetail] = useState<KafkaMessage | null>(null),
    [readError, setReadError] = useState("");
  const [monitoring, setMonitoring] = useState(false),
    [refresh, setRefresh] = useState(0);
  const unauthorized = useRef(props.onUnauthorized);
  unauthorized.current = props.onUnauthorized;

  useEffect(() => {
    const changed = () => {
      const next = readSelected();
      if (selectedRef.current !== next) {
        operation.invalidate();
        setDetail(null);
        setReadError("");
      }
      selectedRef.current = next;
      setSelected(next);
      setComposer(false);
    };
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);

  useEffect(() => {
    setDetail(null);
    setReadError("");
    setMonitoring(false);
    if (!selected) return;
    const controller = new AbortController(),
      until = Date.now() + 20000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Bound even a stalled read. Aborting observation does not cancel a publish.
    const windowTimer = setTimeout(() => {
      controller.abort();
      clearTimeout(timer);
      setMonitoring(false);
    }, 20000);
    setMonitoring(true);
    async function load() {
      if (controller.signal.aborted || Date.now() >= until) return;
      let again = true;
      try {
        const data = await request<KafkaMessage>(
          `/lab/kafka/messages/${encodeURIComponent(selected!)}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted || selectedRef.current !== selected)
          return;
        setDetail(data);
        setReadError("");
        again = data.consumer.status !== "received";
      } catch (e) {
        if (controller.signal.aborted || selectedRef.current !== selected)
          return;
        if (e instanceof ApiError && e.status === 401) {
          clearTimeout(windowTimer);
          setMonitoring(false);
          unauthorized.current();
          return;
        }
        setReadError(
          e instanceof ApiError && e.status === 404
            ? `暂未读到这个消息 ID；不能据此确认它没有发送。稍后可手动刷新。${e.requestId ? `（请求 ID：${e.requestId}）` : ""}`
            : `${message(e)}${e instanceof ApiError && e.requestId ? `（请求 ID：${e.requestId}）` : ""}`,
        );
        again = e instanceof ApiError && e.status === 404;
      }
      if (again && Date.now() < until) {
        timer = setTimeout(load, Math.min(2000, until - Date.now()));
      } else {
        clearTimeout(windowTimer);
        setMonitoring(false);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearTimeout(windowTimer);
    };
  }, [selected, refresh]);

  function openComposer() {
    requestLeave(() => {
      operation.invalidate();
      setNewMessageWarning(!!attempt);
      attemptLock.current = null;
      setAttempt(null);
      setKey("");
      setValue("");
      selectedRef.current = null;
      setSelected(null);
      commitHash("#kafka");
      setComposer(true);
    });
  }

  function closeDrawer() {
    operation.invalidate();
    setComposer(false);
    setKey("");
    setValue("");
    selectedRef.current = null;
    setSelected(null);
    commitHash("#kafka");
  }

  function send(e: FormEvent) {
    e.preventDefault();
    if (
      attemptLock.current ||
      operation.busy ||
      !/^[A-Za-z0-9_-]{1,64}$/.test(key) ||
      !value
    )
      return;
    const id = crypto.randomUUID();
    attemptLock.current = id;
    setAttempt(id);
    setComposer(false);
    // A submitted draft is no longer an unsaved edit. Preserve the known ID in
    // history before the write; inspection and refresh must never resend it.
    selectedRef.current = id;
    setSelected(id);
    commitHash(`#kafka?message=${encodeURIComponent(id)}`);
    void operation.run(
      () =>
        operation.write<KafkaMessage>("/lab/kafka/messages", {
          method: "POST",
          body: JSON.stringify({ id, key, value }),
        }),
      () => {
        list.reset();
        if (selectedRef.current === id) setRefresh((n) => n + 1);
      },
      () => list.refresh(),
    );
  }

  return (
    <div className="lab-resource-workspace">
      <section
        className="lab-panel kafka-history"
        aria-label="已登记的消息"
        data-testid="resource-primary"
      >
        <div className="lab-toolbar">
          <button
            className="primary"
            disabled={operation.busy}
            onClick={openComposer}
          >
            <Send size={15} />
            {attempt ? "开始一条新消息" : "发送消息"}
          </button>
          <ListTools
            loading={list.loading}
            refresh={list.refresh}
            disabled={operation.busy}
          />
        </div>
        <div className="lab-section-title">
          <h2>已登记的消息</h2>
          <span className="lab-small">生产确认与消费者回执分别记录</span>
        </div>
        {list.error && (
          <LabError>
            读取历史失败：{list.error}
            {list.data && " 当前保留上一次读取的列表，并非最新状态。"}
          </LabError>
        )}
        {!list.data ? (
          <Empty>
            {list.loading
              ? "正在读取消息历史…"
              : "尚未取得消息历史，请刷新重试。"}
          </Empty>
        ) : !list.data.items.length ? (
          <Empty>还没有消息记录。发送第一条消息后在这里查看。</Empty>
        ) : (
          <div className="lab-table-scroll">
            <table className="lab-table kafka-history-table">
              <thead>
                <tr>
                  <th>消息 ID</th>
                  <th>消息键</th>
                  <th>正文摘要</th>
                  <th>生产确认</th>
                  <th>消费者回执</th>
                  <th>登记时间</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr
                    key={item.id}
                    data-resource-id={item.id}
                    className={item.id === selected ? "selected" : ""}
                  >
                    <td>
                      <a
                        className="lab-record-link"
                        href={`#kafka?message=${encodeURIComponent(item.id)}`}
                        aria-label={`查看消息 ${item.id}`}
                      >
                        <code>{item.id}</code>
                      </a>
                    </td>
                    <td>
                      <span className="lab-cell-summary">{item.key}</span>
                    </td>
                    <td>
                      <span className="lab-cell-summary">{item.value}</span>
                    </td>
                    <td>
                      <span
                        className={`lab-state ${item.producer.status === "acknowledged" ? "observed" : "neutral"}`}
                      >
                        {item.producer.status === "acknowledged"
                          ? "已确认"
                          : "未确认"}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`lab-state ${item.consumer.status === "received" ? "observed" : "neutral"}`}
                      >
                        {item.consumer.status === "received"
                          ? "已收取"
                          : "尚未观察到"}
                      </span>
                    </td>
                    <td>
                      <time dateTime={item.created_at}>
                        {labTime(item.created_at)}
                      </time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination
          data={list.data}
          offset={list.offset}
          setOffset={list.setOffset}
          disabled={list.loading || operation.busy}
        />
        <p className="lab-help">
          历史由数据库读取；历史回执不代表 broker 现在仍保留消息正文。
        </p>
        {attempt && !selected && (
          <p className="lab-last-attempt">
            上次发送 ID：
            <a href={`#kafka?message=${encodeURIComponent(attempt)}`}>
              <code>{attempt}</code>
            </a>
            。仅查询，不会重发。
          </p>
        )}
      </section>

      <ConsoleDrawer
        key={composer ? "composer" : selected || "closed"}
        open={composer || !!selected}
        title={composer ? "发送消息" : "Kafka 消息详情"}
        onClose={closeDrawer}
        closeLabel={composer ? "关闭发送" : "关闭详情"}
        dirty={composer && !!(key || value)}
        busy={operation.busy}
        wide={!composer}
      >
        {composer ? (
          <div className="lab-editor">
            {newMessageWarning && (
              <p className="lab-help">
                这是另一次发送，可能与此前未确认的消息重复；不会撤销此前发送。
              </p>
            )}
            <form onSubmit={send}>
              <label htmlFor="kafka-key">消息键</label>
              <input
                id="kafka-key"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="例如：lesson"
                required
                maxLength={64}
                pattern="[A-Za-z0-9_-]+"
                disabled={operation.busy}
              />
              <p className="lab-help">1–64 位英文字母、数字、下划线或横线。</p>
              <label htmlFor="kafka-value">消息内容</label>
              <textarea
                id="kafka-value"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="发给后台消费者的一句话"
                rows={7}
                required
                disabled={operation.busy}
              />
              <p className="lab-help">
                最多 4096 UTF-8 字节；仅发送到固定教学 topic。
              </p>
              <div className="lab-actions">
                <button
                  className="primary"
                  disabled={
                    operation.busy ||
                    !/^[A-Za-z0-9_-]{1,64}$/.test(key) ||
                    !value
                  }
                >
                  {operation.busy ? "发送请求中…" : "确认发送"}
                </button>
                <button
                  type="button"
                  className="lab-button"
                  onClick={() => requestLeave(closeDrawer)}
                >
                  取消
                </button>
              </div>
            </form>
          </div>
        ) : selected ? (
          <section className="kafka-detail-content" aria-label="Kafka 消息详情">
            <div className="lab-detail-toolbar">
              <code>{selected}</code>
              <button
                className="lab-button"
                disabled={operation.busy}
                onClick={() => setRefresh((n) => n + 1)}
              >
                <RefreshCw size={14} />
                手动刷新
              </button>
            </div>
            {attempt === selected && (
              <div className="kafka-attempt">
                <span>本次发送 ID（请求前生成并保留）</span>
                <code data-testid="kafka-attempt-id">{attempt}</code>
                <p>
                  {operation.busy
                    ? "发送请求处理中。离开页面不会撤销服务端已收到的发送。"
                    : "每个 ID 只尝试发送一次。未确认时查询原 ID，不会自动重发。"}
                </p>
                {operation.error && (
                  <LabError>
                    {operation.error}
                    <br />
                    发送结果未确认。请按上方 ID 读取记录；这里不会自动重发。
                  </LabError>
                )}
              </div>
            )}
            {readError && (
              <LabError>
                {readError}
                {detail && " 以下保留上次读取的证据，并非当前状态。"}
              </LabError>
            )}
            {detail ? (
              <div data-testid="kafka-detail" data-message-id={detail.id}>
                <section className="lab-detail-section">
                  <h3>消息基本信息</h3>
                  <dl className="lab-metadata">
                    <dt>消息键</dt>
                    <dd>
                      <code>{detail.key}</code>
                    </dd>
                    <dt>Topic</dt>
                    <dd>
                      <code>{detail.topic}</code>
                    </dd>
                    <dt>登记时间</dt>
                    <dd>{labTime(detail.created_at)}</dd>
                    <dt>服务端观察</dt>
                    <dd>{labTime(detail.observed_at)}</dd>
                  </dl>
                  <div className="consumer-payload">
                    <h4>登记的消息正文</h4>
                    <pre>{detail.value}</pre>
                  </div>
                </section>
                <div className="kafka-observations">
                  <article>
                    <h3>生产确认</h3>
                    <strong
                      data-testid="kafka-producer-status"
                      className={`lab-state ${detail.producer.status === "acknowledged" ? "observed" : "neutral"}`}
                    >
                      {detail.producer.status === "acknowledged"
                        ? "已获生产确认"
                        : "未确认"}
                    </strong>
                    <p>
                      {detail.producer.status === "acknowledged"
                        ? "Kafka delivery callback 已确认发送，不等于已消费。"
                        : "没有已保存的生产确认；不能断言消息没有送达。"}
                    </p>
                    <dl>
                      <dt>分区 / offset</dt>
                      <dd>
                        {detail.producer.partition ?? "—"} /{" "}
                        {detail.producer.offset ?? "—"}
                      </dd>
                      <dt>确认时间</dt>
                      <dd>
                        {detail.producer.acknowledged_at
                          ? labTime(detail.producer.acknowledged_at)
                          : "尚无记录"}
                      </dd>
                    </dl>
                  </article>
                  <article>
                    <h3>消费者回执</h3>
                    <strong
                      data-testid="kafka-consumer-status"
                      className={`lab-state ${detail.consumer.status === "received" ? "observed" : "neutral"}`}
                    >
                      {detail.consumer.status === "received"
                        ? "已观察到消费者收取"
                        : "尚未观察到"}
                    </strong>
                    <p>
                      {detail.consumer.status === "received"
                        ? "Worker 实际读取后，回执已写入数据库。"
                        : "尚无已提交的消费回执，不等于消息丢失或 Worker 离线。"}
                    </p>
                    <dl>
                      <dt>消费组</dt>
                      <dd>{detail.consumer.group}</dd>
                      <dt>分区 / offset</dt>
                      <dd>
                        {detail.consumer.partition ?? "—"} /{" "}
                        {detail.consumer.offset ?? "—"}
                      </dd>
                      <dt>收取时间</dt>
                      <dd>
                        {detail.consumer.received_at
                          ? labTime(detail.consumer.received_at)
                          : "尚无记录"}
                      </dd>
                    </dl>
                  </article>
                </div>
                {detail.consumer.status === "received" && (
                  <div className="consumer-payload">
                    <h3>消费者实际收到的内容</h3>
                    <code>{detail.consumer.key}</code>
                    <pre data-testid="kafka-consumer-value">
                      {detail.consumer.value}
                    </pre>
                  </div>
                )}
                <details className="lab-response">
                  <summary>响应详情</summary>
                  <JsonView value={detail} />
                </details>
              </div>
            ) : !readError ? (
              <Empty>
                {monitoring
                  ? "正在按 ID 读取消息记录…"
                  : "尚未取得消息记录。可按原 ID 手动刷新，不会再次发送。"}
              </Empty>
            ) : null}
            <p className="lab-help" role="status">
              {monitoring
                ? "正在短时读取实际回执（最多 20 秒），不是模拟进度。"
                : detail?.consumer.status === "received"
                  ? "已读取到真实收取回执，自动观察已停止。"
                  : "自动观察已暂停，可手动刷新；尚未观察到不代表发送失败。"}
            </p>
            {attempt && (
              <button
                className="lab-button"
                disabled={operation.busy}
                onClick={openComposer}
              >
                开始一条新消息
              </button>
            )}
          </section>
        ) : null}
      </ConsoleDrawer>
    </div>
  );
}
