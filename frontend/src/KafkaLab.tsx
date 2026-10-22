import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, RefreshCw, Send } from "lucide-react";
import { ApiError, message, request } from "./api";
import { type KafkaMessage, type LabProps, labTime } from "./lab";
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
  new URLSearchParams(location.hash.split("?")[1]).get("message");
export default function KafkaLab(props: LabProps) {
  const operation = useLabOperation(props),
    list = useLabList<KafkaMessage>(
      "/lab/kafka/messages",
      props.onUnauthorized,
    );
  const [key, setKey] = useState(""),
    [value, setValue] = useState("");
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
    const changed = () => setSelected(readSelected());
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
    let timer: ReturnType<typeof setTimeout>;
    setMonitoring(true);
    async function load() {
      let again = true;
      try {
        const data = await request<KafkaMessage>(
          `/lab/kafka/messages/${encodeURIComponent(selected!)}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setDetail(data);
        setReadError("");
        again = data.consumer.status !== "received";
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) {
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
      if (again && Date.now() < until)
        timer = setTimeout(load, Math.min(2000, until - Date.now()));
      else setMonitoring(false);
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [selected, refresh]);
  function send(e: FormEvent) {
    e.preventDefault();
    if (attemptLock.current || operation.busy) return;
    const id = crypto.randomUUID();
    attemptLock.current = id;
    setAttempt(id);
    // Persist the known ID in browser history before starting the write, so a
    // refresh/back navigation can inspect uncertain delivery without resending.
    location.hash = `kafka?message=${encodeURIComponent(id)}`;
    setSelected(id);
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
      () => {
        list.refresh();
      },
    );
  }
  return (
    <>
      <div className="lab-workbench-grid">
        <section className="lab-panel lab-editor">
          <div className="lab-section-title">
            <h2>发送一条消息</h2>
            <Send size={18} />
          </div>
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
              disabled={operation.busy || !!attempt}
            />
            <p className="lab-help">1–64 位英文字母、数字、下划线或横线。</p>
            <label htmlFor="kafka-value">消息内容</label>
            <textarea
              id="kafka-value"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="发给后台消费者的一句话"
              rows={5}
              required
              disabled={operation.busy || !!attempt}
            />
            <p className="lab-help">
              最多 4096 UTF-8 字节。使用固定教学 topic，不启动
              Agent、不调用模型，也不提供重放或管理操作。
            </p>
            <button
              className="primary"
              disabled={
                operation.busy ||
                !!attempt ||
                !/^[A-Za-z0-9_-]{1,64}$/.test(key) ||
                !value
              }
            >
              {operation.busy ? "发送请求中…" : "发送消息"}
            </button>
          </form>
          {attempt && (
            <div className="kafka-attempt">
              <span>本次发送 ID（请求前生成并保留）</span>
              <code data-testid="kafka-attempt-id">{attempt}</code>
              <p>
                每个 ID 只尝试发送一次。响应丢失或未确认时，读取这个
                ID，而不是自动重发。
              </p>
              <div className="lab-actions">
                <a
                  className="lab-button"
                  href={`#kafka?message=${attempt}`}
                  onClick={() => {
                    if (selected === attempt) setRefresh((n) => n + 1);
                  }}
                >
                  查看本次消息
                </a>
                <button
                  className="lab-button"
                  disabled={operation.busy}
                  onClick={() => {
                    attemptLock.current = null;
                    setAttempt(null);
                    operation.setError("");
                    setValue("");
                  }}
                >
                  开始一条新消息
                </button>
              </div>
              <small>
                新消息是另一次发送，可能与此前未确认的消息重复；离开页面不会撤销发送。
              </small>
            </div>
          )}
          {operation.error && (
            <LabError>
              {operation.error}
              <br />
              发送结果未确认。请按上方 ID 读取记录；这里不会自动重发。
            </LabError>
          )}
        </section>
        <section className="lab-panel lab-results" aria-label="Kafka 消息详情">
          <div className="lab-section-title">
            <h2>两种确认，分开核对</h2>
            <button
              className="lab-button"
              disabled={!selected || operation.busy}
              onClick={() => setRefresh((n) => n + 1)}
            >
              <RefreshCw size={14} />
              手动刷新
            </button>
          </div>
          {!selected ? (
            <Empty>
              发送一条消息，或从下方历史中选择。生产确认不等于消费者已收到。
            </Empty>
          ) : (
            <>
              <div className="kafka-selected">
                <code>{selected}</code>
                <a href="#kafka" className="lab-button">
                  关闭详情
                </a>
              </div>
              {readError && <LabError>{readError}</LabError>}
              {detail ? (
                <div data-testid="kafka-detail" data-message-id={detail.id}>
                  <div className="kafka-observations">
                    <article>
                      <span>01 · 生产确认</span>
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
                          ? "Kafka delivery callback 已确认这次发送。"
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
                      <span>02 · 消费者收取</span>
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
                  <p className="lab-help">
                    本次服务端观察：{labTime(detail.observed_at)}
                    <br />
                    topic：{detail.topic}
                    <br />
                    消费组：{detail.consumer.group}
                  </p>
                  <details className="lab-response">
                    <summary>查看完整消息与回执</summary>
                    <JsonView value={detail} />
                  </details>
                </div>
              ) : (
                !readError && <Empty>正在按 ID 读取消息记录…</Empty>
              )}
              <p className="lab-help" role="status">
                {monitoring
                  ? "正在短时读取实际回执（最多 20 秒），不是模拟进度。"
                  : detail?.consumer.status === "received"
                    ? "已读取到真实收取回执，自动观察已停止。"
                    : "尚未观察到，可手动刷新。自动观察已停止，不代表发送失败。"}
              </p>
            </>
          )}
        </section>
      </div>
      <section className="lab-panel kafka-history" aria-label="已登记的消息">
        <div className="lab-section-title">
          <h2>已登记的消息</h2>
          <ListTools
            loading={list.loading}
            refresh={list.refresh}
            disabled={operation.busy}
          />
        </div>
        <p className="lab-help">
          从数据库重新读取，刷新页面后仍可查询；历史回执不代表 broker
          现在仍保留消息。
        </p>
        {list.error && (
          <LabError>
            {list.error}
            {list.data && " 当前保留上一次读取的列表。"}
          </LabError>
        )}
        {!list.data ? (
          <Empty>
            {list.loading
              ? "正在读取消息历史…"
              : "暂时无法读取消息历史，请刷新重试。"}
          </Empty>
        ) : !list.data.items.length ? (
          <Empty>还没有消息记录。发送第一条消息后在这里查看。</Empty>
        ) : (
          <div className="kafka-message-list">
            {list.data.items.map((item) => (
              <a
                key={item.id}
                href={`#kafka?message=${item.id}`}
                className={item.id === selected ? "selected" : ""}
              >
                <div>
                  <strong>{item.key}</strong>
                  <p>{item.value}</p>
                  <code>{item.id}</code>
                </div>
                <div>
                  <span>
                    生产：
                    {item.producer.status === "acknowledged"
                      ? "已确认"
                      : "未确认"}
                  </span>
                  <span>
                    消费：
                    {item.consumer.status === "received"
                      ? "已收取"
                      : "尚未观察到"}
                  </span>
                  <ArrowRight size={15} />
                </div>
              </a>
            ))}
          </div>
        )}
        <Pagination
          data={list.data}
          offset={list.offset}
          setOffset={list.setOffset}
          disabled={list.loading || operation.busy}
        />
      </section>
    </>
  );
}
