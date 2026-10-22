import { useEffect, useRef, useState, type FormEvent } from "react";
import { Clock3, KeyRound, Trash2 } from "lucide-react";
import { type LabProps, type RedisSnapshot, labTime } from "./lab";
import {
  DeleteConfirm,
  Empty,
  JsonView,
  LabError,
  useLabOperation,
} from "./LabShared";

export default function RedisLab(props: LabProps) {
  const operation = useLabOperation(props);
  const [key, setKey] = useState(""),
    [value, setValue] = useState(""),
    [ttl, setTtl] = useState("30");
  const [snapshot, setSnapshot] = useState<RedisSnapshot | null>(null),
    [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState(false),
    [now, setNow] = useState(0);
  const deadline = useRef(0),
    autoChecked = useRef<RedisSnapshot | null>(null);
  const validKey = /^[A-Za-z0-9_-]{1,64}$/.test(key),
    validTtl = /^\d+$/.test(ttl) && Number(ttl) >= 1 && Number(ttl) <= 3600;
  function observe(data: RedisSnapshot) {
    deadline.current = performance.now() + Math.max(0, data.ttl_ms);
    setNow(performance.now());
    setSnapshot(data);
  }
  function readKey(readingKey = key) {
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
  }, [snapshot, operation.busy, confirm]);
  function write(e: FormEvent) {
    e.preventDefault();
    if (!validKey || !validTtl) return;
    setNotice("");
    setSnapshot(null);
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
        setNotice("写入后已从服务端回读。再次写入同名键会覆盖值并重置 TTL。");
      },
    );
  }
  const remaining = Math.max(0, Math.ceil((deadline.current - now) / 1000));
  return (
    <div className="component-grid">
      <section className="lab-panel lab-editor">
        <div className="lab-section-title">
          <h2>写入一个临时值</h2>
          <KeyRound size={18} />
        </div>
        <form onSubmit={write}>
          <label htmlFor="redis-key">键名</label>
          <input
            id="redis-key"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setSnapshot(null);
              setNotice("");
              operation.setError("");
            }}
            placeholder="例如：lesson-note"
            required
            maxLength={64}
            pattern="[A-Za-z0-9_-]+"
            disabled={operation.busy}
          />
          <p className="lab-help">
            1–64 位英文字母、数字、下划线或横线。仅操作 lab:kv:
            教学前缀，不提供全库扫描。
          </p>
          <label htmlFor="redis-value">值</label>
          <textarea
            id="redis-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={4}
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
            onChange={(e) => setTtl(e.target.value)}
            disabled={operation.busy}
          />
          <p className="lab-help">
            1–3600 秒；值最多 4096 UTF-8 字节。同名键会被覆盖，不修改任务缓存。
          </p>
          <div className="lab-actions">
            <button
              className="primary"
              disabled={operation.busy || !validKey || !validTtl}
            >
              {operation.busy ? "处理中…" : "写入并设置 TTL"}
            </button>
            <button
              type="button"
              className="lab-button"
              disabled={operation.busy || !validKey}
              onClick={() => {
                setNotice("");
                readKey();
              }}
            >
              读取键值
            </button>
          </div>
        </form>
        {operation.error && <LabError>{operation.error}</LabError>}
        {notice && (
          <p role="status" className="lab-notice">
            {notice}
          </p>
        )}
      </section>
      <section className="lab-panel lab-results" aria-label="Redis 读取结果">
        <div className="lab-section-title">
          <h2>真实值与过期时间</h2>
          <Clock3 size={18} />
        </div>
        {!snapshot ? (
          <Empty>
            {operation.busy ? (
              <span role="status">正在请求 Redis…</span>
            ) : (
              "还没有读取结果。指定一个键，写入或读取后在这里查看。"
            )}
          </Empty>
        ) : (
          <>
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
                      ? `参考倒计时：约 ${remaining} 秒（由服务端 TTL 快照估算）`
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
              <summary>查看完整服务端快照</summary>
              <JsonView value={snapshot} />
            </details>
          </>
        )}
        <div className="lab-actions">
          <button
            className="lab-button"
            disabled={operation.busy || !validKey}
            onClick={() => readKey()}
          >
            再次读取
          </button>
          <button
            className="lab-button danger"
            disabled={operation.busy || !validKey}
            onClick={() => setConfirm(true)}
          >
            <Trash2 size={14} />
            删除键
          </button>
        </div>
      </section>
      {confirm && (
        <DeleteConfirm
          target={key}
          busy={operation.busy}
          cancel={() => setConfirm(false)}
          confirm={() =>
            void operation.run(
              () =>
                operation.write<void>(
                  `/lab/redis/keys/${encodeURIComponent(key)}?confirm=true`,
                  { method: "DELETE" },
                ),
              () => {
                setConfirm(false);
                setSnapshot(null);
                setNotice(
                  "服务端已确认删除请求。可再次读取确认键不存在；已过期的键同样可以安全删除。",
                );
              },
              () => setConfirm(false),
            )
          }
        />
      )}
    </div>
  );
}
