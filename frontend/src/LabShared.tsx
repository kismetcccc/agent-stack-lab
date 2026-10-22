import { useEffect, useRef, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { ApiError, message, request } from "./api";
import type { LabPage, LabProps } from "./lab";

const labMessage = (e: unknown) =>
  `${message(e)}${e instanceof ApiError && e.requestId ? `（请求 ID：${e.requestId}）` : ""}`;

export function LabError({ children }: { children: ReactNode }) {
  return (
    <div className="notice lab-error" role="alert">
      {children}
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="lab-empty">{children}</div>;
}
export function JsonView({ value }: { value: unknown }) {
  return (
    <pre className="lab-json" tabIndex={0}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// Writes are never automatically retried on transport errors. A navigation may hide
// a pending response, but cannot undo a request already received by the server.
export function useLabOperation(props: LabProps) {
  const callbacks = useRef(props);
  callbacks.current = props;
  const mounted = useRef(true),
    lock = useRef(false),
    generation = useRef(0),
    reads = useRef(new AbortController());
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    mounted.current = true;
    reads.current = new AbortController();
    return () => {
      mounted.current = false;
      reads.current.abort();
    };
  }, []);
  async function run<T>(
    operation: () => Promise<T>,
    success: (value: T) => void,
    failed?: (error: unknown) => void,
  ) {
    if (lock.current) return;
    lock.current = true;
    const signal = reads.current.signal;
    const current = generation.current;
    setBusy(true);
    setError("");
    try {
      const value = await operation();
      if (mounted.current && !signal.aborted && generation.current === current)
        success(value);
    } catch (e) {
      if (!mounted.current || signal.aborted || generation.current !== current)
        return;
      if (e instanceof ApiError && e.status === 401)
        callbacks.current.onUnauthorized();
      else {
        setError(labMessage(e));
        failed?.(e);
      }
    } finally {
      if (generation.current === current) {
        lock.current = false;
        if (mounted.current && !signal.aborted) setBusy(false);
      }
    }
  }
  return {
    invalidate: () => {
      generation.current += 1;
      reads.current.abort();
      reads.current = new AbortController();
      lock.current = false;
      setBusy(false);
      setError("");
    },
    busy,
    error,
    setError,
    run,
    read: <T,>(path: string) =>
      request<T>(path, { signal: reads.current.signal }),
    write: <T,>(path: string, options: RequestInit) =>
      callbacks.current.write<T>(path, {
        ...options,
        signal: reads.current.signal,
      }),
  };
}

export function useLabList<T>(path: string, onUnauthorized: () => void) {
  const [data, setData] = useState<LabPage<T> | null>(null),
    [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  const callback = useRef(onUnauthorized);
  callback.current = onUnauthorized;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    request<LabPage<T>>(`${path}?limit=10&offset=${offset}`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (controller.signal.aborted) return;
        if (offset > 0 && !value.items.length && value.total <= offset) {
          setOffset(Math.max(0, Math.ceil(value.total / 10) * 10 - 10));
          return;
        }
        setData(value);
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) callback.current();
        else setError(labMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, offset, revision]);
  return {
    data,
    offset,
    setOffset,
    loading,
    error,
    refresh: () => setRevision((v) => v + 1),
    reset: () => {
      setOffset(0);
      setRevision((v) => v + 1);
    },
  };
}
export function ListTools({
  loading,
  refresh,
  disabled = false,
}: {
  loading: boolean;
  refresh: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      className="lab-button"
      onClick={refresh}
      disabled={loading || disabled}
    >
      <RefreshCw size={14} />
      {loading ? "读取中…" : "刷新列表"}
    </button>
  );
}
export function Pagination({
  data,
  offset,
  setOffset,
  disabled,
}: {
  data: LabPage<unknown> | null;
  offset: number;
  setOffset: (n: number) => void;
  disabled: boolean;
}) {
  if (!data) return null;
  return (
    <div className="lab-pagination">
      <span>共 {data.total} 条 · 每页 10 条</span>
      <div>
        <button
          className="lab-button"
          disabled={disabled || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 10))}
        >
          上一页
        </button>
        <button
          className="lab-button"
          disabled={
            disabled || offset + 10 >= data.total || offset + 10 > 10000
          }
          onClick={() => setOffset(offset + 10)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
export function DeleteConfirm({
  target,
  busy,
  cancel,
  confirm,
}: {
  target: string;
  busy: boolean;
  cancel: () => void;
  confirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    return () => {
      if (before?.isConnected) before.focus();
    };
  }, []);
  return (
    <div className="lab-dialog-backdrop">
      <div
        className="lab-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-title"
        aria-describedby="delete-description"
        ref={panel}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !busy) {
            e.preventDefault();
            cancel();
          }
          if (e.key === "Tab") {
            const buttons = Array.from(
              panel.current?.querySelectorAll<HTMLButtonElement>(
                "button:not(:disabled)",
              ) || [],
            );
            if (!buttons.length) {
              e.preventDefault();
              return;
            }
            const first = buttons[0],
              last = buttons.at(-1);
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <h2 id="delete-title">删除这条教学数据？</h2>
        <p id="delete-description">
          将删除共享空间中的 <strong>{target}</strong>
          。此操作无法撤销，不会删除原有任务或帐号。
        </p>
        <div className="lab-actions">
          <button
            className="lab-button"
            ref={cancelRef}
            disabled={busy}
            onClick={cancel}
          >
            取消
          </button>
          <button
            className="lab-button danger"
            disabled={busy}
            onClick={confirm}
          >
            {busy ? "删除中…" : "确认删除"}
          </button>
        </div>
      </div>
    </div>
  );
}
