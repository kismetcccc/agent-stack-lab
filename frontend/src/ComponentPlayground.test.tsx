// These are explicit network-stub UI unit tests, not real component integration evidence.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import RecordsLab from "./RecordsLab";
import RedisLab from "./RedisLab";
import KafkaLab from "./KafkaLab";
import ComponentPlayground from "./ComponentPlayground";
import App from "./App";
import { request } from "./api";
import type { KafkaMessage, LabWrite } from "./lab";

const json = (data: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 10,
  offset: 0,
});
const id = "00000000-0000-4000-8000-000000000001";
const record = {
  id,
  name: "教学记录",
  value: "从数据库读取",
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
};
const write: LabWrite = (path, options) => request(path, options);
const unauthorized = vi.fn();
const props = { write, onUnauthorized: unauthorized };
const kafka = (overrides: Partial<KafkaMessage> = {}): KafkaMessage => ({
  id,
  topic: "agent.lab.messages.v1",
  key: "lesson",
  value: "server payload",
  created_at: record.created_at,
  observed_at: record.updated_at,
  producer: {
    status: "acknowledged",
    acknowledged_at: record.created_at,
    partition: 0,
    offset: 4,
  },
  consumer: {
    status: "not_observed",
    received_at: null,
    group: "agent-lab-observer-v1",
    partition: null,
    offset: null,
    key: null,
    value: null,
  },
  ...overrides,
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.clearAllMocks();
  history.replaceState(null, "", "/");
});

function setInput(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("direct component shell", () => {
  it("keeps login separate from shared teaching data and labels offline adapters", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(
      <ComponentPlayground
        component="mysql"
        authenticated={false}
        authPanel={<div>existing login</div>}
        mode="test"
        {...props}
      />,
    );
    expect(screen.getByText(/不按帐号隔离/)).toBeInTheDocument();
    expect(screen.getByText(/使用离线 \/ 测试替身/)).toBeInTheDocument();
    expect(screen.getByText("existing login")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "创建记录" }),
    ).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("separates real adapter mode from a deterministic Agent without making lab task requests", async () => {
    location.hash = "#mysql";
    const fetcher = vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/v1/auth/me"
          ? json({
              user: { id: "user", username: "student" },
              csrf_token: "token",
            })
          : path === "/readyz"
            ? json({
                mode: "production",
                model_mode: "deterministic",
                dependencies: { mysql: "up", mongo: "up", kafka: "up" },
              })
            : json(page([])),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await screen.findByRole("button", { name: "创建记录" });
    expect(
      screen.getByText("后端：真实组件适配器（production）"),
    ).toBeInTheDocument();
    expect(screen.getByText(/组件实验完全不使用模型/)).toHaveTextContent(
      "确定性测试控制器（不调用模型）",
    );
    expect(fetcher.mock.calls.some(([path]) => path.includes("/tasks"))).toBe(
      false,
    );
  });
  it("returns unauthorized lab reads to the existing login form", async () => {
    location.hash = "#mysql";
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path === "/api/v1/auth/me"
            ? json({
                user: { id: "user", username: "student" },
                csrf_token: "token",
              })
            : path === "/readyz"
              ? json({ mode: "test" })
              : json({ error: { message: "expired" } }, 401),
        ),
      ),
    );
    render(<App />);
    await screen.findByRole("button", { name: "登录" });
    expect(
      screen.queryByRole("button", { name: "创建记录" }),
    ).not.toBeInTheDocument();
  });
});

describe("persisted records and documents", () => {
  it("renders an honest empty response rather than inserting example data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(page([]))));
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText(/还没有记录/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("prevents repeat writes and uses server readback rather than the input draft", async () => {
    let finish: (response: Response) => void = () => {};
    let rows: unknown[] = [];
    const fetcher = vi.fn((_path: string, options?: RequestInit) =>
      options?.method === "POST"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(json(page(rows))),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText(/还没有记录/);
    setInput("名称", "submitted draft");
    setInput("内容", "input value");
    const button = screen.getByRole("button", { name: "创建记录" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(
      fetcher.mock.calls.filter(([, o]) => o?.method === "POST"),
    ).toHaveLength(1);
    rows = [record];
    await act(async () => finish(json(record, 201)));
    expect(
      await screen.findByRole("button", { name: "编辑 教学记录" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("从数据库读取");
    expect(screen.getByLabelText("名称")).toHaveValue("");
  });
  it("reloads a selected record before editing and cancels without writing", async () => {
    const fetcher = vi.fn((path: string) =>
      Promise.resolve(
        json(
          path.includes("?")
            ? page([record])
            : { ...record, value: "fresh read" },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "编辑 教学记录" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("内容")).toHaveValue("fresh read"),
    );
    fireEvent.click(screen.getByRole("button", { name: "取消编辑" }));
    expect(screen.getByLabelText("内容")).toHaveValue("");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("requires deletion confirmation, supports Escape, and sends explicit confirmation only once", async () => {
    let rows: unknown[] = [record];
    const fetcher = vi.fn((_path: string, options?: RequestInit) => {
      if (options?.method === "DELETE") {
        rows = [];
        return Promise.resolve(json(null, 204));
      }
      return Promise.resolve(json(page(rows)));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "删除 教学记录" }),
    );
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "取消" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([, o]) => o?.method === "DELETE")).toBe(
      false,
    );
    fireEvent.click(screen.getByRole("button", { name: "删除 教学记录" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await screen.findByText(/还没有记录/);
    expect(
      fetcher.mock.calls.filter(([, o]) => o?.method === "DELETE"),
    ).toEqual([
      [
        `/api/v1/lab/mysql/records/${id}?confirm=true`,
        expect.objectContaining({ method: "DELETE" }),
      ],
    ]);
  });
  it("clears stale selection on a real not-found response", async () => {
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path.includes("?")
            ? json(page(reads++ ? [] : [record]))
            : json({ error: { message: "not found", code: "not_found" } }, 404),
        ),
      ),
    );
    render(<RecordsLab kind="mysql" {...props} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "编辑 教学记录" }),
    );
    await screen.findByText(/这条教学数据已不存在/);
    expect(
      screen.queryByRole("button", { name: "保存修改" }),
    ).not.toBeInTheDocument();
  });
  it("keeps failed reads distinct from empty data and shows the backend request ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json(
          {
            error: { message: "数据库暂不可用" },
            request_id: "safe-request-id",
          },
          503,
        ),
      ),
    );
    render(<RecordsLab kind="mysql" {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "safe-request-id",
    );
    expect(screen.queryByText(/还没有记录/)).not.toBeInTheDocument();
  });
  it("aborts pending list reads on navigation/unmount", async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, options: RequestInit) => {
        signal = options.signal as AbortSignal;
        return new Promise<Response>(() => {});
      }),
    );
    const view = render(<RecordsLab kind="mongo" {...props} />);
    expect(signal?.aborted).toBe(false);
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
  it("rejects invalid/root-array JSON before a write and preserves the editor", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(page([])));
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mongo" {...props} />);
    await screen.findByText(/还没有文档/);
    setInput("JSON 文档", '{"unfinished":');
    fireEvent.click(screen.getByRole("button", { name: "保存文档" }));
    expect(screen.getByRole("alert")).toHaveTextContent("JSON 格式不正确");
    setInput("JSON 文档", "[]");
    fireEvent.click(screen.getByRole("button", { name: "保存文档" }));
    expect(screen.getByRole("alert")).toHaveTextContent("必须是 JSON 对象");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("renders server JSON as literal text, never executable HTML", async () => {
    const doc = {
      id,
      document: { title: '<img src=x onerror="alert(1)">' },
      created_at: record.created_at,
      updated_at: record.updated_at,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(page([doc]))));
    render(<RecordsLab kind="mongo" {...props} />);
    await screen.findByRole("button", { name: `编辑文档 ${id}` });
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });
});

describe("Redis observation semantics", () => {
  it("does not call a zero estimate expired until the next server read confirms absence", async () => {
    let finishRead: (response: Response) => void = () => {};
    const fetcher = vi.fn((_path: string, options?: RequestInit) =>
      options?.method === "PUT"
        ? Promise.resolve(
            json({
              key: "lesson",
              exists: true,
              value: "server value",
              ttl_ms: 0,
              observed_at: record.updated_at,
            }),
          )
        : new Promise<Response>((resolve) => {
            finishRead = resolve;
          }),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<RedisLab {...props} />);
    setInput("键名", "lesson");
    setInput("值", "draft");
    fireEvent.click(screen.getByRole("button", { name: "写入并设置 TTL" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(screen.getByText("服务端确认：键存在")).toBeInTheDocument();
    expect(screen.queryByText("服务端确认：键不存在")).not.toBeInTheDocument();
    await act(async () =>
      finishRead(
        json({
          key: "lesson",
          exists: false,
          value: null,
          ttl_ms: -2,
          observed_at: record.updated_at,
        }),
      ),
    );
    expect(await screen.findByText("服务端确认：键不存在")).toBeInTheDocument();
  });
  it("reports missing TTL as an anomaly, not zero or a made-up countdown", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      json({
        key: "lesson",
        exists: true,
        value: "kept",
        ttl_ms: -1,
        observed_at: record.updated_at,
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<RedisLab {...props} />);
    setInput("键名", "lesson");
    fireEvent.click(screen.getByRole("button", { name: "读取键值" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("没有过期时间");
    expect(screen.queryByText(/参考倒计时/)).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not represent dependency failures as absent keys", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json(
            { error: { message: "Redis 暂不可用", code: "redis_unavailable" } },
            503,
          ),
        ),
    );
    render(<RedisLab {...props} />);
    setInput("键名", "lesson");
    fireEvent.click(screen.getByRole("button", { name: "读取键值" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Redis 暂不可用",
    );
    expect(screen.queryByText("服务端确认：键不存在")).not.toBeInTheDocument();
  });
});

describe("Kafka independent observations", () => {
  it("does not turn a producer acknowledgment into consumer receipt", async () => {
    location.hash = `#kafka?message=${id}`;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(json(path.includes("?") ? page([kafka()]) : kafka())),
      ),
    );
    render(<KafkaLab {...props} />);
    expect(
      await screen.findByTestId("kafka-producer-status"),
    ).toHaveTextContent("已获生产确认");
    expect(screen.getByTestId("kafka-consumer-status")).toHaveTextContent(
      "尚未观察到",
    );
    expect(
      screen.queryByTestId("kafka-consumer-value"),
    ).not.toBeInTheDocument();
  });
  it("can show a real consumer receipt while the independent producer fact remains unconfirmed", async () => {
    location.hash = `#kafka?message=${id}`;
    const item = kafka({
      producer: {
        status: "unconfirmed",
        acknowledged_at: null,
        partition: null,
        offset: null,
      },
      consumer: {
        status: "received",
        received_at: record.updated_at,
        group: "agent-lab-observer-v1",
        key: "actual-key",
        value: "actual consumer value",
        partition: 0,
        offset: 4,
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(json(path.includes("?") ? page([item]) : item)),
      ),
    );
    render(<KafkaLab {...props} />);
    expect(
      await screen.findByTestId("kafka-producer-status"),
    ).toHaveTextContent("未确认");
    expect(screen.getByTestId("kafka-consumer-status")).toHaveTextContent(
      "已观察到消费者收取",
    );
    expect(screen.getByTestId("kafka-consumer-value")).toHaveTextContent(
      "actual consumer value",
    );
  });
  it("retains the pre-generated ID on uncertain publish and never resends on refresh", async () => {
    let sentId = "";
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        sentId = JSON.parse(String(options.body)).id;
        return Promise.resolve(
          json(
            {
              error: {
                message: "发送未确认",
                code: "kafka_publish_unconfirmed",
              },
            },
            503,
          ),
        );
      }
      return Promise.resolve(
        json(path.includes("?") ? page([]) : kafka({ id: sentId || id })),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<KafkaLab {...props} />);
    await screen.findByText(/还没有消息记录/);
    setInput("消息键", "lesson");
    setInput("消息内容", "hello");
    const send = screen.getByRole("button", { name: "发送消息" });
    fireEvent.click(send);
    fireEvent.click(send);
    await screen.findByText(/发送结果未确认。请按上方 ID/);
    expect(location.hash).toContain(sentId);
    expect(screen.getByTestId("kafka-attempt-id")).toHaveTextContent(sentId);
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "手动刷新" }));
    await screen.findByTestId("kafka-detail");
    expect(
      fetcher.mock.calls.filter(([, o]) => o?.method === "POST"),
    ).toHaveLength(1);
  });
  it("aborts a previous detail read when browser hash selection changes", async () => {
    location.hash = `#kafka?message=${id}`;
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options?: RequestInit) => {
        if (path.includes("?")) return Promise.resolve(json(page([])));
        signal = options?.signal as AbortSignal;
        return new Promise<Response>(() => {});
      }),
    );
    render(<KafkaLab {...props} />);
    await waitFor(() => expect(signal).toBeDefined());
    await act(async () => {
      location.hash = "#kafka";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByTestId("kafka-detail")).not.toBeInTheDocument();
  });
});

describe("lab CSRF navigation cancellation", () => {
  it("does not replay a rejected write after navigation while CSRF refresh is pending", async () => {
    location.hash = "#mysql";
    let authReads = 0,
      finishRefresh: (response: Response) => void = () => {};
    let refreshSignal: AbortSignal | undefined;
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (path === "/api/v1/auth/me") {
        authReads += 1;
        if (authReads === 1)
          return Promise.resolve(
            json({
              user: { id: "user", username: "student" },
              csrf_token: "old-token",
            }),
          );
        refreshSignal = options?.signal as AbortSignal;
        // Deliberately ignore abort here: the application must still check it
        // before replaying, even if a response races with navigation.
        return new Promise<Response>((resolve) => {
          finishRefresh = resolve;
        });
      }
      if (path === "/readyz") return Promise.resolve(json({ mode: "test" }));
      if (options?.method === "POST")
        return Promise.resolve(
          json({ error: { message: "rotated", code: "csrf_failed" } }, 403),
        );
      return Promise.resolve(json(page([])));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await screen.findByRole("button", { name: "创建记录" });
    setInput("名称", "cancel-before-retry");
    fireEvent.click(screen.getByRole("button", { name: "创建记录" }));
    await waitFor(() => expect(authReads).toBe(2));
    await act(async () => {
      location.hash = "#redis";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await screen.findByLabelText("键名");
    expect(refreshSignal?.aborted).toBe(true);
    await act(async () =>
      finishRefresh(
        json({
          user: { id: "user", username: "student" },
          csrf_token: "fresh-token",
        }),
      ),
    );
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "POST"),
    ).toHaveLength(1);
    expect(screen.getByTestId("component-redis")).toBeInTheDocument();
  });
  it("retries one explicit CSRF failure with identical lab body only while still active", async () => {
    location.hash = "#mysql";
    let authReads = 0,
      writes = 0;
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (path === "/api/v1/auth/me")
        return Promise.resolve(
          json({
            user: { id: "user", username: "student" },
            csrf_token: ++authReads === 1 ? "old-token" : "new-token",
          }),
        );
      if (path === "/readyz") return Promise.resolve(json({ mode: "test" }));
      if (options?.method === "POST")
        return Promise.resolve(
          ++writes === 1
            ? json({ error: { message: "rotated", code: "csrf_failed" } }, 403)
            : json(record, 201),
        );
      return Promise.resolve(json(page(writes > 1 ? [record] : [])));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await screen.findByRole("button", { name: "创建记录" });
    setInput("名称", "same-body");
    fireEvent.click(screen.getByRole("button", { name: "创建记录" }));
    await screen.findByRole("button", { name: "编辑 教学记录" });
    const calls = fetcher.mock.calls.filter(
      ([, options]) => options?.method === "POST",
    );
    expect(calls).toHaveLength(2);
    expect(calls[0][1]?.body).toEqual(calls[1][1]?.body);
    expect(calls[1][1]?.headers).toMatchObject({ "X-CSRF-Token": "new-token" });
  });
});

describe("honest uncertain and bounded states", () => {
  it("retains a failed write draft and asks to verify rather than claiming it was saved", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, options?: RequestInit) =>
        Promise.resolve(
          options?.method === "POST"
            ? json({ error: { message: "write response unavailable" } }, 503)
            : json(page([])),
        ),
      ),
    );
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText(/还没有记录/);
    setInput("名称", "keep my draft");
    fireEvent.click(screen.getByRole("button", { name: "创建记录" }));
    await screen.findByText(/写入结果可能尚未确认/);
    expect(screen.getByLabelText("名称")).toHaveValue("keep my draft");
    expect(screen.queryByText(/服务端已保存/)).not.toBeInTheDocument();
  });
  it("stops Kafka polling after the observation window without declaring failed delivery", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    history.replaceState(null, "", `/#kafka?message=${id}`);
    const fetcher = vi.fn((path: string) =>
      Promise.resolve(json(path.includes("?") ? page([kafka()]) : kafka())),
    );
    vi.stubGlobal("fetch", fetcher);
    await act(async () => {
      render(<KafkaLab {...props} />);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(21000);
    });
    expect(
      screen.getByText(/尚未观察到，可手动刷新。自动观察已停止/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("kafka-consumer-status")).toHaveTextContent(
      "尚未观察到",
    );
    const count = fetcher.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(21000);
    });
    expect(fetcher).toHaveBeenCalledTimes(count);
  });
  it("does not describe a lab 404 fallback as another account's private task", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 404)));
    await expect(request("/lab/mysql/records/missing")).rejects.toThrow(
      "教学数据或实验接口不存在",
    );
  });
});
