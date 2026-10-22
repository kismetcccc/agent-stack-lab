import { useEffect, useRef, useState, type FormEvent } from "react";
import { Clock3, KeyRound, Search, Trash2 } from "lucide-react";
import { type LabProps, type RedisSnapshot, labTime } from "./lab";
import ConsoleDrawer from "./ConsoleDrawer";
import { ApiError } from "./api";
import {
  DeleteConfirm,
  Empty,
  JsonView,
  LabError,
  useLabOperation,
} from "./LabShared";

const isKey = (value: string) => /^[A-Za-z0-9_-]{1,64}$/.test(value);

export default function RedisLab(props: LabProps) {
  const operation = useLabOperation(props);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState(false),
    [key, setKey] = useState(""),
    [initialKey, setInitialKey] = useState(""),
    [value, setValue] = useState(""),
    [ttl, setTtl] = useState("30"),
    [submitted, setSubmitted] = useState(false);
  const [snapshot, setSnapshot] = useState<RedisSnapshot | null>(null),
    [stale, setStale] = useState(false),
    [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null),
    [now, setNow] = useState(0);
  const deadline = useRef(0),
    autoChecked = useRef<RedisSnapshot | null>(null);
  const validTtl = /^\d+$/.test(ttl) && Number(ttl) >= 1 && Number(ttl) <= 3600;
  const dirty =
    !submitted && (key !== initialKey || value !== "" || ttl !== "30");

  function observe(data: RedisSnapshot) {
    deadline.current = performance.now() + Math.max(0, data.ttl_ms);
    setNow(performance.now());
    setSnapshot(data);
    setStale(false);
  }
  function readKey(readingKey = query) {
    if (!isKey(readingKey)) return;
    setStale(!!snapshot);
    void operation.run(
      () =>
        operation.read<RedisSnapshot>(
          `/lab/redis/keys/${encodeURIComponent(readingKey)}`,
        ),
      observe,
    );
  }
  useEffect(() => {
    if (!snapshot?.exists || snapshot.ttl_ms < 0) return;
    const timer = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(timer);
  }, [snapshot]);
  useEffect(() => {
    if (
      !snapshot?.exists ||
      snapshot.ttl_ms < 0 ||
      operation.busy ||
      confirm ||
      editor ||
      autoChecked.current === snapshot
    )
      return;
    const timer = setTimeout(
      () => {
        autoChecked.current = snapshot;
        readKey(snapshot.key);
      },
      Math.max(100, deadline.current - performance.now() + 50),
    );
    return () => clearTimeout(timer);
  }, [snapshot, operation.busy, confirm, editor]);

  function openEditor() {
    setInitialKey(query);
    setKey(query);
    setValue("");
    setTtl("30");
    setSubmitted(false);
    operation.setError("");
    setNotice("");
    setEditor(true);
  }
  function closeEditor() {
    if (submitted) {
      // Keep the exact attempted key available after an uncertain write. Hiding
      // its response cannot undo a request already received by the server.
      setQuery(key);
      if (snapshot?.key !== key) setSnapshot(null);
      setNotice(
        `键 ${key} 的写入请求可能已到达服务端。关闭不会撤销写入，请读取键值确认。`,
      );
    }
    operation.invalidate();
    setEditor(false);
    setKey("");
    setValue("");
    setTtl("30");
    setSubmitted(false);
  }
  function write(e: FormEvent) {
    e.preventDefault();
    if (!isKey(key) || !validTtl || operation.busy) return;
    setNotice("");
    setStale(!!snapshot);
    setSubmitted(true);
    void operation.run(
      () =>
        operation.write<RedisSnapshot>(
          `/lab/redis/keys/${encodeURIComponent(key)}`,
          {
            method: "PUT",
            body: JSON.stringify({ value, ttl_seconds: Number(ttl) }),
          },
        ),
      (data) => {
        observe(data);
        setQuery(data.key);
        setEditor(false);
        setValue("");
        setNotice("写入后已从服务端回读。下方为本次键值与 TTL 快照。");
      },
      (error) => {
        if (
          error instanceof ApiError &&
          [400, 403, 413, 422].includes(error.status)
        ) {
          // Explicit rejection is not an uncertain transport result; the input
          // remains an unsubmitted draft and retains the normal close guard.
          setSubmitted(false);
        } else {
          setNotice(
            "写入未获确认。请先按原键名查询核对，不会自动重试；关闭不会撤销已送达的请求。",
          );
        }
      },
    );
  }
  const remaining = Math.max(0, Math.ceil((deadline.current - now) / 1000));

  return (
    <div className="lab-resource-workspace redis-workspace">
      <section className="lab-panel" aria-label="Redis 精确键查询">
        <div className="lab-toolbar redis-query-toolbar">
          <form
            className="redis-query"
            onSubmit={(e) => {
              e.preventDefault();
              setNotice("");
              readKey();
            }}
          >
            <label htmlFor="redis-query">查询键名</label>
            <input
              id="redis-query"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSnapshot(null);
                setStale(false);
                setNotice("");
                operation.setError("");
              }}
              placeholder="输入完整键名，例如 lesson-note"
              required
              maxLength={64}
              pattern="[A-Za-z0-9_-]+"
              disabled={operation.busy}
            />
            <button
              className="lab-button"
              disabled={operation.busy || !isKey(query)}
            >
              <Search size={15} />{" "}
              {operation.busy && !editor ? "读取中…" : "读取键值"}
            </button>
          </form>
          <button
            className="primary"
            onClick={openEditor}
            disabled={operation.busy}
          >
            <KeyRound size={15} /> 写入键值
          </button>
        </div>
        <p className="lab-help">
          精确查询 lab:kv: 教学键；不提供全库扫描，不操作任务缓存。
        </p>
      </section>

      {!editor && operation.error && (
        <LabError>
          {operation.error}
          {snapshot && " 当前保留上次快照，并非最新状态。"}
        </LabError>
      )}
      {!editor && notice && (
        <p role="status" className="lab-notice">
          {notice}
        </p>
      )}
      <section
        className="lab-panel lab-results"
        aria-label="Redis 读取结果"
        data-testid="resource-primary"
      >
        <div className="lab-section-title">
          <h2>键值快照</h2>
          <Clock3 size={18} />
        </div>
        {!snapshot ? (
          <Empty>
            {operation.busy ? (
              <span role="status">正在请求 Redis…</span>
            ) : operation.error ? (
              "尚未取得服务端快照。读取失败不表示键不存在。"
            ) : (
              "尚未查询。输入完整键名，查看服务端返回的值与 TTL。"
            )}
          </Empty>
        ) : (
          <>
            {stale && (
              <p className="lab-help">
                上次读取快照 · {operation.busy ? "正在重新确认" : "非当前状态"}
              </p>
            )}
            <div
              className="redis-result"
              data-testid="redis-observation"
              data-key={snapshot.key}
              data-exists={snapshot.exists}
              data-ttl-ms={snapshot.ttl_ms}
            >
              <code className="redis-key">{snapshot.key}</code>
              <span
                className={`lab-state ${snapshot.exists ? "observed" : "neutral"}`}
              >
                {snapshot.exists
                  ? "服务端确认：键存在"
                  : "服务端确认：键不存在"}
              </span>
            </div>
            <p className="lab-help">
              服务端观察时间：{labTime(snapshot.observed_at)}
            </p>
            {snapshot.exists ? (
              <>
                <div className="redis-value">
                  <span>实际读到的值</span>
                  <pre>
                    {snapshot.value === "" ? "（空字符串）" : snapshot.value}
                  </pre>
                </div>
                <div className="ttl-fact">
                  <span>服务端 TTL 快照</span>
                  <strong data-testid="redis-ttl">
                    {snapshot.ttl_ms} <small>ms</small>
                  </strong>
                </div>
                {snapshot.ttl_ms >= 0 ? (
                  <p className="lab-help" role="status">
                    {remaining > 0
                      ? `参考倒计时：约 ${remaining} 秒（本地估算）`
                      : operation.busy
                        ? "预计 TTL 已到，正在向服务端确认…"
                        : "预计 TTL 已到，尚未确认是否过期。请再次读取。"}
                    <br />
                    倒计时归零不是过期证据；到时会实际读取一次，仍以新响应为准。
                  </p>
                ) : (
                  <LabError>
                    此键没有过期时间（TTL = -1）。这是异常观察，不会伪造倒计时。
                  </LabError>
                )}
              </>
            ) : (
              <Empty>
                最新读取确认此键不存在：可能已过期、已被删除，或从未写入。TTL ={" "}
                {snapshot.ttl_ms} ms。
              </Empty>
            )}
            <details className="lab-response">
              <summary>响应详情</summary>
              <JsonView value={snapshot} />
            </details>
            <div className="lab-actions">
              <button
                className="lab-button"
                disabled={operation.busy}
                onClick={() => {
                  setNotice("");
                  readKey(snapshot.key);
                }}
              >
                再次读取
              </button>
              <button
                className="lab-button danger"
                disabled={operation.busy}
                onClick={() => setConfirm(snapshot.key)}
              >
                <Trash2 size={14} /> 删除键
              </button>
            </div>
          </>
        )}
      </section>

      <ConsoleDrawer
        open={editor}
        title="写入键值"
        onClose={closeEditor}
        dirty={dirty}
        busy={operation.busy}
      >
        <div className="lab-editor">
          <form onSubmit={write}>
            <label htmlFor="redis-key">键名</label>
            <input
              id="redis-key"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setSubmitted(false);
              }}
              placeholder="例如：lesson-note"
              required
              maxLength={64}
              pattern="[A-Za-z0-9_-]+"
              disabled={operation.busy}
            />
            <p className="lab-help">1–64 位英文字母、数字、下划线或横线。</p>
            <label htmlFor="redis-value">值</label>
            <textarea
              id="redis-value"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setSubmitted(false);
              }}
              rows={5}
              placeholder="写入一段临时保存的文字"
              disabled={operation.busy}
            />
            <label htmlFor="redis-ttl">过期时间（秒）</label>
            <input
              id="redis-ttl"
              type="number"
              min={1}
              max={3600}
              step={1}
              required
              value={ttl}
              onChange={(e) => {
                setTtl(e.target.value);
                setSubmitted(false);
              }}
              disabled={operation.busy}
            />
            <p className="lab-help">
              1–3600 秒；值最多 4096 UTF-8 字节。同名键会覆盖原值并重置 TTL。
            </p>
            <div className="lab-actions">
              <button
                className="primary"
                disabled={operation.busy || !isKey(key) || !validTtl}
              >
                {operation.busy ? "处理中…" : "写入并设置 TTL"}
              </button>
            </div>
          </form>
          {operation.error && <LabError>{operation.error}</LabError>}
          {notice && (
            <p role="status" className="lab-notice">
              {notice}
            </p>
          )}
          {operation.busy && (
            <p className="lab-help">
              请勿重复提交。离开页面不会撤销服务端已收到的写入。
            </p>
          )}
        </div>
      </ConsoleDrawer>
      {confirm && (
        <DeleteConfirm
          target={confirm}
          busy={operation.busy}
          cancel={() => setConfirm(null)}
          confirm={() => {
            const deleting = confirm;
            setStale(!!snapshot);
            void operation.run(
              () =>
                operation.write<void>(
                  `/lab/redis/keys/${encodeURIComponent(deleting)}?confirm=true`,
                  { method: "DELETE" },
                ),
              () => {
                setConfirm(null);
                setSnapshot(null);
                setQuery(deleting);
                setNotice(
                  "服务端已确认删除请求。请读取键值确认当前是否存在；删除响应不代替再次读取。",
                );
              },
              () => setConfirm(null),
            );
          }}
        />
      )}
    </div>
  );
}
