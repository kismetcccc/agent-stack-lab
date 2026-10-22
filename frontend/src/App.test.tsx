// Unit tests use explicit network stubs, not evidence of real backend integration.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import { Explorer } from "./Explorer";
import { ApiError, request } from "./api";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  location.hash = "";
});
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
describe("API client", () => {
  it("sends same-origin cookies and preserves CSRF headers", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ id: "task" }));
    vi.stubGlobal("fetch", fetcher);
    await request("/tasks", {
      method: "POST",
      headers: { "X-CSRF-Token": "csrf", "Idempotency-Key": "stable" },
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/tasks",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({
          "X-CSRF-Token": "csrf",
          "Idempotency-Key": "stable",
        }),
      }),
    );
  });
  it("exposes authorization errors without rendering server HTML", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json({ error: { message: "forbidden" } }, 403)),
    );
    await expect(request("/tasks/private")).rejects.toEqual(
      new ApiError(403, "forbidden"),
    );
  });
});
describe("component teaching explorer", () => {
  it("never invents Redis or Worker health from successful readiness", () => {
    render(
      <Explorer
        roleId="redis"
        onRole={() => {}}
        health={{ dependencies: { mysql: "up", mongo: "up", kafka: "up" } }}
      />,
    );
    expect(
      screen.getByText("未提供实时探针 / 通过任务观察"),
    ).toBeInTheDocument();
    expect(screen.getByText(/cache_status：hit/)).toBeInTheDocument();
    expect(screen.queryByText("就绪检查通过")).not.toBeInTheDocument();
  });
  it("distinguishes lightweight SQL from actual MySQL", () => {
    render(
      <Explorer
        roleId="mysql"
        onRole={() => {}}
        health={{ dependencies: { sqlite: "up" } }}
      />,
    );
    expect(screen.getByText("SQLite 替代 · 非 MySQL")).toBeInTheDocument();
  });
  it("selects roles and separates synchronous reads", () => {
    const select = vi.fn();
    render(<Explorer roleId="api" onRole={select} health={null} />);
    fireEvent.click(screen.getByRole("button", { name: /02.*MySQL/ }));
    expect(select).toHaveBeenCalledWith("mysql");
    fireEvent.click(screen.getByRole("tab", { name: /查询与结果/ }));
    expect(
      screen.getByText("GET /api/v1/tasks/:id/results"),
    ).toBeInTheDocument();
    expect(screen.getByText(/先校验所有权/)).toBeInTheDocument();
  });
});
describe("anonymous task workspace", () => {
  it("keeps the direct playground public and requires login for component data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path === "/readyz"
            ? json({
                mode: "demo",
                model_mode: "deterministic",
                dependencies: { sqlite: "up" },
              })
            : json({ error: { message: "unauthorized" } }, 401),
        ),
      ),
    );
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "选一个组件，动手试一次。" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/后端：demo/)).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
  });
  it("disables duplicate authentication while request is pending", async () => {
    location.hash = "#lab";
    let resolveAuth: (r: Response) => void = () => {};
    const fetcher = vi.fn((path: string) =>
      path.endsWith("/register")
        ? new Promise<Response>((r) => {
            resolveAuth = r;
          })
        : Promise.resolve(
            path === "/readyz" ? json({ mode: "test" }) : json({}, 401),
          ),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await screen.findByLabelText("用户名");
    fireEvent.click(screen.getByRole("button", { name: "没有帐号？创建帐号" }));
    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "student" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "testpassword" },
    });
    const button = screen.getByRole("button", { name: "注册并登录" });
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(
      fetcher.mock.calls.filter(([p]) => p.endsWith("/register")),
    ).toHaveLength(1);
    resolveAuth(json({ error: { message: "username taken" } }, 409));
    await screen.findByText("username taken");
  });
});

describe("resource lifecycle", () => {
  it("aborts pending detail reads when the user pauses polling", async () => {
    location.hash = "#lab?task=delayed";
    let detailSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path === "/api/v1/auth/me")
          return Promise.resolve(
            json({
              user: { id: "u", username: "student" },
              csrf_token: "csrf",
            }),
          );
        if (path === "/readyz")
          return Promise.resolve(
            json({ mode: "test", model_mode: "deterministic" }),
          );
        if (path.startsWith("/api/v1/tasks?"))
          return Promise.resolve(json({ items: [], total: 0 }));
        detailSignal = options?.signal as AbortSignal;
        return new Promise<Response>((_resolve, reject) =>
          detailSignal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        );
      }),
    );
    render(<App />);
    await waitFor(() => expect(detailSignal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "暂停自动刷新" }));
    await waitFor(() => expect(detailSignal?.aborted).toBe(true));
    expect(screen.queryByTestId("report-content")).not.toBeInTheDocument();
    expect(
      screen.getByText("自动刷新已暂停。恢复后读取所选任务。"),
    ).toBeInTheDocument();
  });
  it("aborts selected resource reads on close and never keeps a stale report", async () => {
    location.hash = "#lab?task=private";
    let detailSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path === "/api/v1/auth/me")
          return Promise.resolve(
            json({
              user: { id: "u", username: "student" },
              csrf_token: "csrf",
            }),
          );
        if (path === "/readyz") return Promise.resolve(json({ mode: "test" }));
        if (path.startsWith("/api/v1/tasks?"))
          return Promise.resolve(json({ items: [], total: 0 }));
        detailSignal = options?.signal as AbortSignal;
        return new Promise<Response>((_resolve, reject) =>
          detailSignal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        );
      }),
    );
    render(<App />);
    await waitFor(() => expect(detailSignal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "关闭任务详情" }));
    await waitFor(() => expect(detailSignal?.aborted).toBe(true));
    expect(screen.queryByTestId("task-detail")).not.toBeInTheDocument();
  });
});

describe("identity and bounded CSRF recovery", () => {
  const userA = { user: { id: "a", username: "alice" }, csrf_token: "old" };
  const userB = { user: { id: "b", username: "bob" }, csrf_token: "b-token" };
  const task = {
    id: "created",
    prompt: "a task",
    status: "pending",
    attempt_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    result_available: false,
    model_mode: "deterministic",
    trace_id: "trace",
    progress: 0,
    error: null,
  };
  const otherwise = (path: string) =>
    path === "/readyz"
      ? json({ mode: "test" })
      : path.endsWith("/events") || path.endsWith("/attempts")
        ? json({ items: [] })
        : path.includes("?")
          ? json({ items: [], total: 0 })
          : json(task);
  it("refreshes only csrf_failed once and keeps the exact task key/body", async () => {
    location.hash = "#lab";
    let me = 0;
    const writes: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path.endsWith("/auth/me"))
          return Promise.resolve(
            json(++me === 1 ? userA : { ...userA, csrf_token: "fresh" }),
          );
        if (path === "/api/v1/tasks" && options?.method === "POST") {
          writes.push(options);
          return Promise.resolve(
            writes.length === 1
              ? json(
                  { error: { code: "csrf_failed", message: "CSRF 校验失败" } },
                  403,
                )
              : json(task, 202),
          );
        }
        return Promise.resolve(otherwise(path));
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("研究主题 / 任务要求"), {
      target: { value: "a task" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交报告任务" }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(me).toBe(2);
    expect(writes[0].body).toBe(writes[1].body);
    expect(
      (writes[0].headers as Record<string, string>)["Idempotency-Key"],
    ).toBe((writes[1].headers as Record<string, string>)["Idempotency-Key"]);
    expect((writes[1].headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "fresh",
    );
  });
  it("does not loop repeated csrf failures", async () => {
    location.hash = "#lab";
    let me = 0;
    let writes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path.endsWith("/auth/me")) {
          me++;
          return Promise.resolve(json(userA));
        }
        if (path === "/api/v1/tasks" && options?.method === "POST") {
          writes++;
          return Promise.resolve(
            json(
              {
                error: { code: "csrf_failed", message: "CSRF rejected again" },
              },
              403,
            ),
          );
        }
        return Promise.resolve(otherwise(path));
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("研究主题 / 任务要求"), {
      target: { value: "a task" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交报告任务" }));
    await screen.findByText("CSRF rejected again");
    expect(writes).toBe(2);
    expect(me).toBe(2);
    expect(screen.getByLabelText("研究主题 / 任务要求")).toHaveValue("a task");
  });
  it("blocks submit during pending logout and recovers logout CSRF once", async () => {
    location.hash = "#lab";
    let me = 0;
    let logout = 0;
    let resolveLogout: (r: Response) => void = () => {};
    let submits = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path.endsWith("/auth/me")) {
          me++;
          return Promise.resolve(json(userA));
        }
        if (path.endsWith("/auth/logout")) {
          logout++;
          return logout === 1
            ? Promise.resolve(
                json(
                  { error: { code: "csrf_failed", message: "expired" } },
                  403,
                ),
              )
            : new Promise<Response>((r) => {
                resolveLogout = r;
              });
        }
        if (path === "/api/v1/tasks" && options?.method === "POST") {
          submits++;
          return Promise.resolve(json(task));
        }
        return Promise.resolve(otherwise(path));
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("研究主题 / 任务要求"), {
      target: { value: "private draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await waitFor(() => expect(logout).toBe(2));
    const submit = screen.getByRole("button", { name: "提交报告任务" });
    expect(submit).toBeDisabled();
    fireEvent.submit(submit.closest("form")!);
    expect(submits).toBe(0);
    expect(me).toBe(2);
    resolveLogout(new Response(null, { status: 204 }));
    await screen.findByLabelText("用户名");
    expect(screen.queryByDisplayValue("private draft")).not.toBeInTheDocument();
  });
  it.each([401, 202])(
    "expires drafts and ignores delayed old status %s after a new login",
    async (status) => {
      location.hash = "#lab";
      let lists = 0;
      let resolveOld: (r: Response) => void = () => {};
      vi.stubGlobal(
        "fetch",
        vi.fn((path: string, options?: RequestInit) => {
          if (path.endsWith("/auth/me")) return Promise.resolve(json(userA));
          if (path.endsWith("/auth/login")) return Promise.resolve(json(userB));
          if (path.startsWith("/api/v1/tasks?"))
            return Promise.resolve(
              ++lists === 2
                ? json({ error: { message: "expired" } }, 401)
                : json({ items: [], total: 0 }),
            );
          if (path === "/api/v1/tasks" && options?.method === "POST")
            return new Promise<Response>((r) => {
              resolveOld = r;
            });
          return Promise.resolve(otherwise(path));
        }),
      );
      render(<App />);
      fireEvent.change(await screen.findByLabelText("研究主题 / 任务要求"), {
        target: { value: "alice secret draft" },
      });
      fireEvent.click(screen.getByRole("button", { name: "提交报告任务" }));
      fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
      await screen.findByLabelText("用户名");
      fireEvent.change(screen.getByLabelText("用户名"), {
        target: { value: "bob" },
      });
      fireEvent.change(screen.getByLabelText("密码"), {
        target: { value: "testpassword" },
      });
      fireEvent.click(screen.getByRole("button", { name: "登录" }));
      const prompt = await screen.findByLabelText("研究主题 / 任务要求");
      expect(prompt).toHaveValue("");
      fireEvent.change(prompt, { target: { value: "bob draft" } });
      await act(async () => {
        resolveOld(
          status === 401
            ? json({ error: { message: "old 401" } }, 401)
            : json(task, 202),
        );
      });
      await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
      expect(prompt).toHaveValue("bob draft");
      expect(screen.queryByText("old 401")).not.toBeInTheDocument();
    },
  );
  it("does not resubmit an old task if CSRF refresh discovers a different user", async () => {
    location.hash = "#lab";
    let me = 0;
    let writes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path.endsWith("/auth/me"))
          return Promise.resolve(json(++me === 1 ? userA : userB));
        if (path === "/api/v1/tasks" && options?.method === "POST") {
          writes++;
          return Promise.resolve(
            json({ error: { code: "csrf_failed", message: "expired" } }, 403),
          );
        }
        return Promise.resolve(otherwise(path));
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("研究主题 / 任务要求"), {
      target: { value: "alice private" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交报告任务" }));
    await screen.findByText("其他标签页切换了帐号，请重新登录；旧草稿已清除。");
    expect(writes).toBe(1);
    expect(screen.queryByDisplayValue("alice private")).not.toBeInTheDocument();
  });
});
it("never attempts CSRF recovery for a resource-permission 403", async () => {
  location.hash = "#lab";
  let me = 0;
  let posts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, options?: RequestInit) => {
      if (path.endsWith("/auth/me")) {
        me++;
        return Promise.resolve(
          json({ user: { id: "u", username: "student" }, csrf_token: "csrf" }),
        );
      }
      if (path === "/readyz") return Promise.resolve(json({ mode: "test" }));
      if (options?.method === "POST") {
        posts++;
        return Promise.resolve(
          json({ error: { code: "forbidden", message: "资源权限不足" } }, 403),
        );
      }
      return Promise.resolve(json({ items: [], total: 0 }));
    }),
  );
  render(<App />);
  fireEvent.change(await screen.findByLabelText("研究主题 / 任务要求"), {
    target: { value: "task prompt" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交报告任务" }));
  await screen.findByText("资源权限不足");
  expect(me).toBe(1);
  expect(posts).toBe(1);
});

it("keeps a completed detail snapshot in the list when an older list response arrives later", async () => {
  location.hash = "#lab?task=latest";
  const base = {
    id: "latest",
    prompt: "真实详情优先于旧列表快照",
    attempt_count: 0,
    status: "pending",
    created_at: "2026-10-22T03:00:00.000000",
    updated_at: "2026-10-22T03:00:00.000000",
    result_available: false,
    model_mode: "deterministic",
    trace_id: "trace",
    progress: 0,
    error: null,
  };
  const completed = {
    ...base,
    status: "succeeded",
    attempt_count: 1,
    updated_at: "2026-10-22T03:00:02.000000",
    result_available: true,
  };
  let resolveList: (r: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      if (path.endsWith("/auth/me"))
        return Promise.resolve(
          json({ user: { id: "u", username: "student" }, csrf_token: "csrf" }),
        );
      if (path === "/readyz") return Promise.resolve(json({ mode: "test" }));
      if (path.startsWith("/api/v1/tasks?"))
        return new Promise<Response>((r) => {
          resolveList = r;
        });
      if (path.endsWith("/events") || path.endsWith("/attempts"))
        return Promise.resolve(json({ items: [] }));
      if (path.endsWith("/results"))
        return Promise.resolve(
          json({ content: "真实报告", cache_status: "hit" }),
        );
      return Promise.resolve(json(completed));
    }),
  );
  render(<App />);
  await screen.findByTestId("report-content");
  await act(async () => resolveList(json({ items: [base], total: 1 })));
  const row = screen.getByRole("button", { name: /真实详情优先于旧列表快照/ });
  expect(row).toHaveTextContent("已完成");
  expect(row).toHaveTextContent("尝试 1");
  expect(row).not.toHaveTextContent("等待分发");
});
