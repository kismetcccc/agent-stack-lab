import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowRight,
  BookOpen,
  Box,
  FlaskConical,
  GitBranch,
  LogOut,
  Play,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  ApiError,
  message,
  request,
  type Session,
  type Step,
  type Task,
  type TaskResult,
} from "./api";
import { chapters, components, statusNames } from "./content";
import { Explorer } from "./Explorer";
import AgentActions, { controllerLabel } from "./AgentActions";
import PlaygroundHome, { playgrounds, type Readiness } from "./PlaygroundHome";
import ConsoleShell, { consoleRoute } from "./ConsoleShell";
import ConsoleDrawer from "./ConsoleDrawer";
import { commitHash, useConsoleNavigation } from "./navigation";
import ComponentPlayground from "./ComponentPlayground";
const formatTime = (s: string) =>
  new Date(s).toLocaleString("zh-CN", { hour12: false });
const stringify = (v: unknown) =>
  typeof v === "string" ? v : JSON.stringify(v, null, 2);
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge status-${status}`}>
      {statusNames[status] || status}
    </span>
  );
}
function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="notice" role="alert">
      {children}
    </div>
  );
}
function App() {
  useConsoleNavigation();
  const [creating, setCreating] = useState(false),
    [authOpen, setAuthOpen] = useState(false),
    [taskHelp, setTaskHelp] = useState(false);
  const submitController = useRef<AbortController | null>(null);
  const readPage = () => location.hash.slice(1).split("?")[0] || "playground";
  const [page, setPage] = useState(readPage);
  const [selected, setSelected] = useState(
    new URLSearchParams(location.hash.split("?")[1]).get("task"),
  );
  const [session, setSession] = useState<Session | null>(null),
    [boot, setBoot] = useState(true),
    [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authError, setAuthError] = useState(""),
    [authBusy, setAuthBusy] = useState(false),
    authLock = useRef(false);
  const [readiness, setReadiness] = useState<Readiness>({
    data: null,
    receivedAt: null,
    httpStatus: null,
    loading: true,
    error: "",
    stale: false,
  });
  const [healthRefresh, setHealthRefresh] = useState(0);
  const health = readiness.data;
  const [polling, setPolling] = useState(true);
  const [attempts, setAttempts] = useState<
    {
      id: string;
      fence: number;
      started_at: string;
      finished_at: string | null;
      outcome: string;
    }[]
  >([]);
  const [resultMeta, setResultMeta] = useState<{
    execution_kind?: string;
    controller_mode?: string;
  } | null>(null);
  const [cache, setCache] = useState<{ status: string; time: string } | null>(
    null,
  );
  const [tasks, setTasks] = useState<Task[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [listError, setListError] = useState(""),
    [listLoading, setListLoading] = useState(false),
    [refresh, setRefresh] = useState(0);
  const [task, setTask] = useState<Task | null>(null),
    [events, setEvents] = useState<Step[]>([]),
    [result, setResult] = useState(""),
    [detailError, setDetailError] = useState(""),
    [detailLoading, setDetailLoading] = useState(false);
  const [prompt, setPrompt] = useState(""),
    [submitting, setSubmitting] = useState(false),
    [submitError, setSubmitError] = useState("");
  const submitLock = useRef(false),
    idempotency = useRef<{ prompt: string; key: string } | null>(null);
  const latestDetails = useRef(new Map<string, Task>());
  const identityEpoch = useRef(0);
  const sessionRef = useRef<Session | null>(null);
  const authOperation = useRef(0);
  const submitOperation = useRef(0);
  // Identity changes are a privacy boundary, including background 401 expiry.
  function applySession(next: Session | null) {
    if (sessionRef.current?.user.id !== next?.user.id) {
      identityEpoch.current += 1;
      submitController.current?.abort();
      setCreating(false);
      setTaskHelp(false);
      setAuthOpen(false);
      authOperation.current += 1;
      submitOperation.current += 1;
      authLock.current = false;
      submitLock.current = false;
      setAuthBusy(false);
      setSubmitting(false);
      setPrompt("");
      idempotency.current = null;
      setSubmitError("");
      setAuthError("");
      latestDetails.current.clear();
      setTasks([]);
      setTotal(0);
      setOffset(0);
      setTask(null);
      setEvents([]);
      setAttempts([]);
      setResult("");
      setCache(null);
      setResultMeta(null);
      setListError("");
      setDetailError("");
    }
    if (!next) setAuthMode("login");
    sessionRef.current = next;
    setSession(next);
  }
  async function authenticatedWrite<T>(
    path: string,
    options: RequestInit,
    epoch: number,
  ): Promise<T> {
    const ensureActive = () => {
      if (options.signal?.aborted)
        throw new DOMException("Aborted", "AbortError");
    };
    ensureActive();
    const current = sessionRef.current;
    if (!current) throw new ApiError(401, "会话已失效，请重新登录。");
    const send = (token: string) => {
      ensureActive();
      return request<T>(path, {
        ...options,
        headers: { ...options.headers, "X-CSRF-Token": token },
      });
    };
    try {
      return await send(current.csrf_token);
    } catch (error) {
      if (
        !(error instanceof ApiError) ||
        error.code !== "csrf_failed" ||
        identityEpoch.current !== epoch
      )
        throw error;
      // Only an explicit CSRF failure may refresh and retry once, never arbitrary 403s.
      const refreshed = await request<Session>("/auth/me", {
        signal: options.signal,
      });
      ensureActive();
      if (identityEpoch.current !== epoch)
        throw new Error("身份已变化，旧请求已忽略。");
      if (refreshed.user.id !== current.user.id) {
        applySession(null);
        setAuthError("其他标签页切换了帐号，请重新登录；旧草稿已清除。");
        throw new Error("会话身份已变化，未重试旧任务。");
      }
      applySession(refreshed);
      return send(refreshed.csrf_token);
    }
  }
  const nav = useCallback((p: string, id?: string) => {
    location.hash = `${p}${id ? `?task=${encodeURIComponent(id)}` : ""}`;
  }, []);
  useEffect(() => {
    const onHash = () => {
      setPage(readPage());
      setSelected(new URLSearchParams(location.hash.split("?")[1]).get("task"));
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const c = new AbortController();
    const epoch = identityEpoch.current;
    request<Session>("/auth/me", { signal: c.signal })
      .then((value) => {
        if (!c.signal.aborted && identityEpoch.current === epoch)
          applySession(value);
      })
      .catch((e) => {
        if (
          e.name !== "AbortError" &&
          !(e instanceof ApiError && e.status === 401)
        )
          setAuthError(message(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setBoot(false);
      });
    return () => c.abort();
  }, []);
  useEffect(() => {
    let stopped = false;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      setReadiness((old) => ({ ...old, loading: true }));
      try {
        const response = await fetch("/readyz", { signal: c.signal });
        const data = await response.json();
        if (!data || typeof data !== "object" || Array.isArray(data))
          throw new Error("invalid readiness");
        if (!stopped)
          setReadiness({
            data,
            receivedAt: new Date().toISOString(),
            httpStatus: response.status,
            loading: false,
            stale: false,
            error: response.ok
              ? ""
              : "部分依赖未就绪；以下为本次接口返回的证据。",
          });
      } catch {
        if (!stopped)
          setReadiness((old) => ({
            ...old,
            loading: false,
            stale: !!old.data,
            error: "无法取得有效健康检查响应；当前服务状态未知。",
          }));
      }
      if (!stopped) timer = setTimeout(load, 15000);
    };
    void load();
    return () => {
      stopped = true;
      c.abort();
      clearTimeout(timer);
    };
  }, [healthRefresh]);
  useEffect(() => {
    if (!session) {
      latestDetails.current.clear();
      setTasks([]);
      setTotal(0);
      return;
    }
    if (!polling || page !== "lab") {
      setListLoading(false);
      return;
    }
    const epoch = identityEpoch.current;
    let stopped = false;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setListLoading(true);
    const load = async () => {
      try {
        const data = await request<{ items: Task[]; total: number }>(
          `/tasks?limit=10&offset=${offset}`,
          { signal: c.signal },
        );
        if (!stopped && identityEpoch.current === epoch) {
          // A slower list snapshot cannot regress a newer accepted detail response.
          setTasks(
            data.items.map((item) => {
              const detail = latestDetails.current.get(item.id);
              return detail && detail.updated_at >= item.updated_at
                ? detail
                : item;
            }),
          );
          setTotal(data.total);
          setListError("");
        }
      } catch (e) {
        if (!stopped && identityEpoch.current === epoch) {
          setListError(message(e));
          if (e instanceof ApiError && e.status === 401) applySession(null);
        }
      } finally {
        if (!stopped && identityEpoch.current === epoch) {
          setListLoading(false);
          if (polling) timer = setTimeout(load, 3000);
        }
      }
    };
    void load();
    return () => {
      stopped = true;
      c.abort();
      clearTimeout(timer);
    };
  }, [session, offset, refresh, polling, page]);
  useEffect(() => {
    // Clear selected-resource data even while polling is paused.
    setTask(null);
    setEvents([]);
    setResult("");
    setAttempts([]);
    setCache(null);
    setResultMeta(null);
    setDetailError("");
    setDetailLoading(false);
  }, [selected, session, page]);
  useEffect(() => {
    // Each effect owns its timer and abort signal; older resources cannot overwrite newer navigation.
    if (!polling || !selected || !session || page !== "lab") return;
    const epoch = identityEpoch.current;
    let stopped = false;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setDetailLoading(true);
    const load = async () => {
      try {
        const t = await request<Task>(
          `/tasks/${encodeURIComponent(selected)}`,
          { signal: c.signal },
        );
        const e = await request<{ items: Step[] }>(
          `/tasks/${encodeURIComponent(selected)}/events`,
          { signal: c.signal },
        );
        const a = await request<{
          items: {
            id: string;
            fence: number;
            started_at: string;
            finished_at: string | null;
            outcome: string;
          }[];
        }>(`/tasks/${encodeURIComponent(selected)}/attempts`, {
          signal: c.signal,
        });
        let r = "";
        let cacheValue: string | null = null;
        let nextMeta: {
          execution_kind?: string;
          controller_mode?: string;
        } | null = null;
        if (t.result_available && t.status === "succeeded") {
          const data = await request<TaskResult>(
            `/tasks/${encodeURIComponent(selected)}/results`,
            {
              signal: c.signal,
            },
          );
          r = stringify(data.content);
          cacheValue = data.cache_status;
          nextMeta = {
            execution_kind: data.execution_kind,
            controller_mode: data.controller_mode,
          };
        }
        if (!stopped && identityEpoch.current === epoch) {
          latestDetails.current.set(t.id, t);
          setTasks((items) =>
            items.map((item) =>
              item.id === t.id && t.updated_at >= item.updated_at ? t : item,
            ),
          );
          setTask(t);
          setEvents(e.items);
          setAttempts(a.items);
          setResult(r);
          setResultMeta(nextMeta);
          if (cacheValue)
            setCache({ status: cacheValue, time: new Date().toISOString() });
          setDetailError("");
          if (polling && !["succeeded", "failed"].includes(t.status))
            timer = setTimeout(load, 1500);
        }
      } catch (e) {
        if (!stopped && identityEpoch.current === epoch) {
          setDetailError(message(e));
          if (e instanceof ApiError && e.status === 401) applySession(null);
        }
      } finally {
        if (!stopped && identityEpoch.current === epoch)
          setDetailLoading(false);
      }
    };
    void load();
    return () => {
      stopped = true;
      c.abort();
      clearTimeout(timer);
      setDetailLoading(false);
    };
  }, [selected, session, page, refresh, polling]);
  async function auth(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (authLock.current || submitLock.current) return;
    const epoch = identityEpoch.current;
    const operation = ++authOperation.current;
    authLock.current = true;
    setAuthBusy(true);
    setAuthError("");
    const form = new FormData(e.currentTarget);
    try {
      const value = await request<Session>(`/auth/${authMode}`, {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      if (identityEpoch.current === epoch) applySession(value);
    } catch (error) {
      if (identityEpoch.current === epoch) setAuthError(message(error));
    } finally {
      if (authOperation.current === operation) {
        authLock.current = false;
        setAuthBusy(false);
      }
    }
  }
  async function logout() {
    if (authLock.current || submitLock.current || !sessionRef.current) return;
    const epoch = identityEpoch.current;
    const logoutFrom = location.hash;
    const operation = ++authOperation.current;
    authLock.current = true;
    setAuthBusy(true);
    try {
      await authenticatedWrite("/auth/logout", { method: "POST" }, epoch);
      if (identityEpoch.current !== epoch) return;
      applySession(null);
      if (location.hash === logoutFrom)
        nav(page === "lab" ? "lab" : "playground");
    } catch (error) {
      if (identityEpoch.current !== epoch) return;
      if (error instanceof ApiError && error.status === 401) applySession(null);
      else setAuthError(message(error));
    } finally {
      if (authOperation.current === operation) {
        authLock.current = false;
        setAuthBusy(false);
      }
    }
  }
  function closeCreate() {
    // Abort only our response/CSRF recovery path; a delivered write is not undone.
    submitController.current?.abort();
    submitOperation.current += 1;
    submitLock.current = false;
    setSubmitting(false);
    setCreating(false);
    setPrompt("");
    setSubmitError("");
    idempotency.current = null;
  }
  useEffect(() => {
    closeCreate();
    setAuthOpen(false);
    setTaskHelp(false);
  }, [page, selected]);
  useEffect(() => () => submitController.current?.abort(), []);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (submitLock.current || authLock.current || !sessionRef.current) return;
    const epoch = identityEpoch.current;
    const operation = ++submitOperation.current;
    const controller = new AbortController();
    submitController.current = controller;
    submitLock.current = true;
    setSubmitting(true);
    setSubmitError("");
    const submittedFrom = location.hash;
    const value = prompt.trim();
    if (!idempotency.current || idempotency.current.prompt !== value)
      idempotency.current = { prompt: value, key: crypto.randomUUID() };
    try {
      // The exact body and key survive a single bounded CSRF recovery attempt.
      const t = await authenticatedWrite<Task>(
        "/tasks",
        {
          method: "POST",
          signal: controller.signal,
          headers: { "Idempotency-Key": idempotency.current.key },
          body: JSON.stringify({ prompt: value }),
        },
        epoch,
      );
      if (
        identityEpoch.current !== epoch ||
        controller.signal.aborted ||
        submitOperation.current !== operation
      )
        return;
      setPrompt("");
      idempotency.current = null;
      setOffset(0);
      setRefresh((v) => v + 1);
      if (location.hash === submittedFrom) {
        setCreating(false);
        commitHash(`lab?task=${encodeURIComponent(t.id)}`);
      }
    } catch (error) {
      if (
        identityEpoch.current !== epoch ||
        controller.signal.aborted ||
        submitOperation.current !== operation
      )
        return;
      if (error instanceof ApiError && error.status === 401) applySession(null);
      else setSubmitError(message(error));
    } finally {
      if (submitOperation.current === operation) {
        submitLock.current = false;
        setSubmitting(false);
      }
    }
  }
  const authPanel = (
    <div className="auth-box">
      <h3>{authMode === "login" ? "登录实验室" : "创建教学帐号"}</h3>
      <p>
        {page === "lab"
          ? "任务属于当前帐号。会话通过 HttpOnly Cookie 保存。"
          : "登录后直接操作。实验数据在本地帐号间共享，不按帐号隔离。"}
      </p>
      {boot ? (
        <p role="status">正在检查登录状态…</p>
      ) : (
        <form onSubmit={auth}>
          <label>
            用户名
            <input
              name="username"
              autoComplete="username"
              required
              minLength={3}
              maxLength={80}
              pattern="[A-Za-z0-9_-]+"
              title="3 至 80 位英文字母、数字、下划线或横线"
              disabled={authBusy}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete={
                authMode === "register" ? "new-password" : "current-password"
              }
              required
              minLength={10}
              maxLength={128}
              disabled={authBusy}
            />
          </label>
          {authError && <Notice>{authError}</Notice>}
          <button className="primary full" disabled={authBusy}>
            {authBusy
              ? "正在处理…"
              : authMode === "login"
                ? "登录"
                : "注册并登录"}
          </button>
          <button
            type="button"
            className="text-button"
            disabled={authBusy}
            onClick={() => {
              setAuthMode(authMode === "login" ? "register" : "login");
              setAuthError("");
            }}
          >
            {authMode === "login" ? "没有帐号？创建帐号" : "已有帐号？返回登录"}
          </button>
        </form>
      )}
      <small>仅用于本地教学；未提供找回密码、邮箱验证或 MFA。</small>
    </div>
  );
  return (
    <ConsoleShell
      page={page}
      account={
        session ? (
          <>
            <span className="avatar">
              {session.user.username.slice(0, 1).toUpperCase()}
            </span>
            <span>{session.user.username}</span>
            <button
              className="icon-button"
              aria-label="退出登录"
              disabled={authBusy || submitting}
              onClick={logout}
            >
              <LogOut size={17} />
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setAuthOpen(true)}
            disabled={boot}
          >
            {boot ? "检查会话中…" : "登录帐号"}
          </button>
        )
      }
    >
      {authError && session && <Notice>{authError}</Notice>}
      {page === "playground" ? (
        <PlaygroundHome
          readiness={readiness}
          onRefresh={() => setHealthRefresh((n) => n + 1)}
        />
      ) : playgrounds.some((item) => item.id === page) ? (
        <ComponentPlayground
          key={`${page}:${identityEpoch.current}`}
          component={page}
          authenticated={!!session}
          authPanel={authPanel}
          mode={health?.mode}
          write={(path, options) =>
            authenticatedWrite(path, options, identityEpoch.current)
          }
          onUnauthorized={() => applySession(null)}
        />
      ) : consoleRoute(page).id === "overview" ? (
        <Explorer
          roleId={page.replace("architecture-", "")}
          onRole={(id) => nav(`architecture-${id}`)}
          health={readiness.stale ? null : health}
        />
      ) : page === "lab" ? (
        <section className="console-tasks">
          <div className="console-page-heading">
            <div>
              <h1>任务与 Agent</h1>
              <p>提交任务，查看服务端状态、生命周期与已提交的 Agent 动作。</p>
            </div>
            <span className="console-tag">当前帐号</span>
          </div>
          {!session ? (
            <section className="console-surface composer">{authPanel}</section>
          ) : (
            <>
              <div className="console-toolbar console-task-toolbar">
                <button
                  className="primary"
                  onClick={() => setCreating(true)}
                  disabled={authBusy}
                >
                  <Play size={15} />
                  新建任务
                </button>
                <div className="console-actions">
                  <button
                    className="icon-button"
                    aria-label="刷新任务"
                    disabled={listLoading}
                    onClick={() => setRefresh((n) => n + 1)}
                  >
                    <RefreshCw size={16} />
                  </button>
                  <button onClick={() => setTaskHelp(true)}>帮助</button>
                </div>
              </div>
              <section className="console-surface tasks-panel">
                <div className="section-heading">
                  <h2>
                    我的任务 <span className="count">{total}</span>
                  </h2>
                  <span className="muted">每页 10 条 · 服务端分页</span>
                </div>
                {listError && (
                  <Notice>
                    {listError}
                    {tasks.length > 0 && "（保留上次列表，非最新状态）"}
                  </Notice>
                )}
                {listLoading && tasks.length === 0 ? (
                  <div className="empty" role="status">
                    正在加载任务…
                  </div>
                ) : tasks.length === 0 ? (
                  <div className="empty">
                    <Box size={25} />
                    <strong>
                      {listError ? "未取得任务列表" : "还没有任务"}
                    </strong>
                    <p>
                      {listError
                        ? "请重新读取；读取失败不代表列表为空。"
                        : "点击新建任务，提交第一份教学材料。"}
                    </p>
                  </div>
                ) : (
                  <div className="console-table-scroll">
                    <table
                      className="console-table console-task-table"
                      aria-label="我的任务"
                    >
                      <thead>
                        <tr>
                          <th>任务</th>
                          <th>状态</th>
                          <th>尝试</th>
                          <th>创建时间</th>
                          <th>ID</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((item) => (
                          <tr key={item.id}>
                            <td>
                              <button
                                className={`task-row ${selected === item.id ? "selected" : ""}`}
                                onClick={() => nav("lab", item.id)}
                              >
                                <span className="task-title">
                                  {item.prompt}
                                </span>
                                <span className="visually-hidden">
                                  {statusNames[item.status] || item.status} ·
                                  尝试 {item.attempt_count}
                                </span>
                              </button>
                            </td>
                            <td>
                              <Badge status={item.status} />
                            </td>
                            <td>{item.attempt_count}</td>
                            <td>{formatTime(item.created_at)}</td>
                            <td>
                              <code className="console-id" title={item.id}>
                                {item.id}
                              </code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {total > 10 && (
                  <div className="pagination">
                    <button
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - 10))}
                    >
                      上一页
                    </button>
                    <span>
                      {Math.floor(offset / 10) + 1} / {Math.ceil(total / 10)}
                    </span>
                    <button
                      disabled={offset + 10 >= total}
                      onClick={() => setOffset(offset + 10)}
                    >
                      下一页
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
          <ConsoleDrawer
            open={creating && !!session}
            title="新建任务"
            onClose={closeCreate}
            dirty={!!prompt.trim()}
            busy={submitting}
          >
            <div className="composer">
              <p className="console-mode-note">
                Agent：
                {health?.model_mode === "deterministic"
                  ? "deterministic 确定性测试控制器（不调用模型）"
                  : health?.model_mode || "模式未知；请先确认服务端配置"}
              </p>
              <form onSubmit={submit}>
                <label htmlFor="prompt">研究主题 / 任务要求</label>
                <textarea
                  id="prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={
                    "目标：[search:销量] [stats]\n材料：销量 10 20 30"
                  }
                  required
                  minLength={3}
                  maxLength={4000}
                  rows={5}
                  disabled={submitting || authBusy}
                />
                <div className="input-meta">
                  <span>不提交密码、密钥或敏感资料</span>
                  <span>{prompt.length} / 4000</span>
                </div>
                {submitError && <Notice>{submitError}</Notice>}
                <button
                  className="primary full"
                  disabled={submitting || authBusy || prompt.trim().length < 3}
                >
                  <Play size={16} />
                  {submitting ? "正在提交…" : "提交报告任务"}
                </button>
                <p className="form-hint">
                  脚本示例：目标：[search:销量] [stats]；材料：销量 10 20
                  30。脚本测试无真实模型推理。提交后通过真实 API
                  轮询；中断网络时重试沿用幂等键，避免重复创建任务。
                </p>
              </form>
            </div>
          </ConsoleDrawer>
          <ConsoleDrawer
            open={!!selected && !creating && !!session}
            title="任务详情"
            closeLabel="关闭任务详情"
            onClose={() => nav("lab")}
            wide
          >
            <section className="panel trace-panel">
              <div className="section-heading">
                <div>
                  <h2>执行轨迹</h2>
                </div>
                <button
                  className="poll-button"
                  aria-pressed={polling}
                  onClick={() => setPolling(!polling)}
                >
                  {polling ? "暂停自动刷新" : "恢复自动刷新"}
                </button>
              </div>
              {!selected ? (
                <div className="trace-empty">
                  <div className="trace-orbit">
                    <GitBranch size={32} />
                  </div>
                  <h3>一条任务，一条可追溯的链路。</h3>
                  <p>
                    选择左侧任务，查看真实状态、组件事件和结果。
                    <br />
                    没有计时模拟，也没有虚构的成功记录。
                  </p>
                  <div className="trace-tags">
                    <span>task_id</span>
                    <span>trace_id</span>
                    <span>event_id</span>
                  </div>
                </div>
              ) : !session ? (
                <div className="empty">
                  请登录以查看此任务；每次查询都会验证任务所有权。
                </div>
              ) : (
                <>
                  {!polling && !task && (
                    <div className="empty">
                      自动刷新已暂停。恢复后读取所选任务。
                    </div>
                  )}
                  {detailLoading && !task && (
                    <div className="empty" role="status">
                      正在读取任务与事件…
                    </div>
                  )}
                  {detailError && (
                    <Notice>
                      {detailError}
                      <button
                        className="text-button"
                        onClick={() => setRefresh((v) => v + 1)}
                      >
                        重新读取
                      </button>
                    </Notice>
                  )}
                  {task && (
                    <>
                      <div className="task-summary" data-testid="task-detail">
                        <div>
                          <Badge status={task.status} />
                          <span className="model-tag">
                            {task.model_mode === "deterministic"
                              ? "确定性测试 · 非真实模型"
                              : task.model_mode}
                          </span>
                        </div>
                        <h3>{task.prompt}</h3>
                        <dl>
                          <dt>task_id</dt>
                          <dd>{task.id}</dd>
                          <dt>trace_id</dt>
                          <dd>{task.trace_id}</dd>
                          <dt>执行尝试</dt>
                          <dd>
                            {task.attempt_count} 次 ·{" "}
                            {formatTime(task.updated_at)}
                          </dd>
                        </dl>
                        {task.error && <Notice>{stringify(task.error)}</Notice>}
                      </div>
                      <div className="timeline-heading">
                        <h3>后台生命周期</h3>
                        <span>MySQL 中持久化的生命周期记录</span>
                      </div>
                      <p className="event-disclaimer">
                        组件字段表示写入事件的模块，不代表捕获了每个网络请求。记录不包含模型隐藏思维。
                      </p>
                      <ol className="timeline" data-testid="task-events">
                        {events.map((e) => (
                          <li key={e.id}>
                            <span className="timeline-dot" />
                            <div className="event-top">
                              <strong>
                                {e.component ? `${e.component} · ` : ""}
                                {e.kind}
                              </strong>
                              <time>{formatTime(e.created_at)}</time>
                            </div>
                            <pre>{stringify(e.content)}</pre>
                            <details>
                              <summary>关联标识</summary>
                              <code>
                                event_id: {e.id}
                                <br />
                                task_id: {e.task_id}
                                <br />
                                trace_id: {e.trace_id || task.trace_id}
                              </code>
                            </details>
                          </li>
                        ))}
                      </ol>
                      {events.length === 0 && (
                        <div className="empty compact">
                          暂未记录事件。任务状态仍以数据库返回为准。
                        </div>
                      )}
                      <details className="attempts" data-testid="task-attempts">
                        <summary>执行尝试 · {attempts.length}</summary>
                        {attempts.length === 0 ? (
                          <p>尚无执行尝试</p>
                        ) : (
                          attempts.map((a) => (
                            <div key={a.id}>
                              <strong>
                                Fence {a.fence} · {a.outcome || "执行中"}
                              </strong>
                              <code>{a.id}</code>
                              <small>
                                {formatTime(a.started_at)} →{" "}
                                {a.finished_at
                                  ? formatTime(a.finished_at)
                                  : "尚未结束"}
                              </small>
                            </div>
                          ))
                        )}
                      </details>
                      <AgentActions
                        key={`${task.id}:${identityEpoch.current}`}
                        task={task}
                        polling={polling}
                        refreshKey={refresh}
                        sessionEpoch={identityEpoch.current}
                        onUnauthorized={(epoch) => {
                          if (identityEpoch.current === epoch)
                            applySession(null);
                        }}
                      />
                      {task.status === "succeeded" && task.result_available ? (
                        <div className="result">
                          <div>
                            <BookOpen size={18} />
                            <h3>研究报告</h3>
                            <span>纯文本安全呈现</span>
                          </div>
                          <p
                            className="cache-status"
                            data-testid="cache-status"
                          >
                            Redis 缓存：{cache?.status || "未知"} · 查询时间{" "}
                            {cache ? formatTime(cache.time) : "未知"}
                            <br />
                            此状态来自本次结果读取，不是持续在线探针。
                          </p>
                          <p
                            className="result-execution-mode"
                            data-testid="result-execution-mode"
                          >
                            {controllerLabel(
                              resultMeta?.execution_kind,
                              resultMeta?.controller_mode,
                            )}
                          </p>
                          <pre data-testid="report-content">{result}</pre>
                        </div>
                      ) : (
                        <div className="result-pending">
                          {task.status === "failed"
                            ? "任务未成功，不展示正式结果。"
                            : "结果将在任务成功且结果引用提交后显示。"}
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
            </section>
          </ConsoleDrawer>
          <ConsoleDrawer
            open={taskHelp}
            title="任务与 Agent · 帮助"
            onClose={() => setTaskHelp(false)}
          >
            <h3>提交与观察</h3>
            <p>
              任务归当前帐号所有。状态、生命周期、执行尝试和结果从 API
              读取，不显示模拟进度。
            </p>
            <h3>执行模式</h3>
            <p>
              deterministic / scripted_test 是脚本测试，不是 LLM
              推理；旧结果保留原执行类型。只有成功提交的 Agent 动作可查询。
            </p>
            <h3>安全边界</h3>
            <p>
              不提交秘密或隐私材料。不提供取消、删除、强制重试或任意工具执行。网络中断后相同草稿重试沿用幂等键；关闭页面不撤销已经送达的任务。
            </p>
            <a href="#overview">查看架构说明</a>
          </ConsoleDrawer>
        </section>
      ) : page === "learn" ? (
        <div className="chapter-grid">
          {chapters.map((c) => (
            <article className="panel chapter" key={c.tag}>
              <span className="eyebrow">{c.tag}</span>
              <h2>{c.title}</h2>
              <p>{c.body}</p>
              <a href="#lab">
                在实验室观察 <ArrowRight size={15} />
              </a>
            </article>
          ))}
        </div>
      ) : page === "experiments" ? (
        <>
          <div className="experiment-intro panel">
            <FlaskConical size={28} />
            <div>
              <h2>先观察，再动手</h2>
              <p>
                以下是故障实验说明，不是已执行结果。请按照仓库 docs
                中的命令在隔离开发环境操作；页面不会擅自停止服务。每个实验都要记录前提、实际事件和恢复结果。
              </p>
            </div>
          </div>
          <div className="chapter-grid">
            {components.map((c) => (
              <article className="panel chapter" key={c.id}>
                <span className="eyebrow">{c.name} / FAILURE LAB</span>
                <h2>{c.label}</h2>
                <p>{c.experiment}</p>
                <div className="experiment-check">
                  <strong>验证边界</strong>
                  <p>{c.boundary}</p>
                </div>
                <a href="#lab">
                  查看实际调用链 <ArrowRight size={15} />
                </a>
              </article>
            ))}
          </div>
          <div className="panel caution">
            <ShieldCheck size={22} />
            <p>
              <strong>准确区分验收层次</strong>
              <br />
              SQLite、内存总线或确定性模型测试通过，不代表 MySQL / Kafka /
              MongoDB / Redis 的真实集成通过；部署清单也不代表 Kubernetes
              已验证。
            </p>
          </div>
        </>
      ) : (
        <section className="console-surface console-not-found">
          <h1>未找到页面</h1>
          <p>这个地址没有对应的工作区。</p>
          <a href="#playground">回到总览</a>
        </section>
      )}
      <ConsoleDrawer
        open={authOpen && !session}
        title="登录帐号"
        onClose={() => setAuthOpen(false)}
      >
        <div className="composer">{authPanel}</div>
      </ConsoleDrawer>
    </ConsoleShell>
  );
}
export default App;
