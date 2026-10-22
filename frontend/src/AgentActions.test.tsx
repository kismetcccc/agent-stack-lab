// Explicit component fixtures validate rendering and isolation, not backend execution.
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import AgentActions, { controllerLabel, publicText } from "./AgentActions";
import type { Task, AgentStepsResponse } from "./api";
const task: Task = {
  id: "a",
  prompt: "目标：统计",
  status: "succeeded",
  attempt_count: 1,
  created_at: "2026-10-22",
  updated_at: "2026-10-22",
  error: null,
  result_available: true,
  model_mode: "deterministic",
  trace_id: "trace",
  progress: 100,
};
const props = {
  task,
  polling: true,
  refreshKey: 0,
  sessionEpoch: 1,
  onUnauthorized: vi.fn(),
};
const base = {
  task_id: "a",
  attempt_id: "attempt-a",
  created_at: "2026-10-22",
  execution_kind: "single_agent",
  controller_mode: "scripted_test",
};
const committed: AgentStepsResponse = {
  availability: "committed",
  execution_kind: "single_agent",
  controller_mode: "scripted_test",
  items: [
    {
      ...base,
      id: "s1",
      sequence: 1,
      kind: "tool_call",
      content: "调用工具",
      tool_name: "read_text",
      arguments: { offset: 0, length: 100 },
    },
    {
      ...base,
      id: "s2",
      sequence: 2,
      kind: "tool_result",
      content: "观察",
      tool_name: "read_text",
      result: {
        text: "<img src=x onerror=alert(1)>",
        reasoning: "hidden-value",
        nested: { thought: "hidden-nested" },
      },
      truncated: true,
    },
    { ...base, id: "s3", sequence: 3, kind: "final", content: "公开最终答复" },
  ],
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
describe("committed Agent actions", () => {
  it("renders bounded public actions as text and labels scripted execution honestly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(committed)));
    const { container } = render(<AgentActions {...props} />);
    await screen.findByText("脚本测试策略 · 无真实模型推理");
    expect(screen.getAllByTestId("agent-step")).toHaveLength(3);
    expect(screen.getByLabelText("工具参数")).toHaveTextContent("offset");
    expect(screen.getByLabelText("工具结果")).toHaveTextContent(
      "<img src=x onerror=alert(1)>",
    );
    expect(container.querySelector("img")).toBeNull();
    expect(
      screen.queryByText(/hidden-value|hidden-nested/),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/工具返回已按预算截取/)).toBeInTheDocument();
    expect(screen.getByLabelText("最终答复摘要")).toHaveTextContent(
      "公开最终答复",
    );
  });
  it.each(["not_committed", "legacy"] as const)(
    "shows %s as its own availability, never an empty success",
    async (availability) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(json({ ...committed, availability })),
      );
      render(<AgentActions {...props} />);
      await screen.findByTestId(
        availability === "legacy" ? "agent-legacy" : "agent-not-committed",
      );
      expect(screen.queryByTestId("agent-step")).not.toBeInTheDocument();
      expect(screen.queryByText("公开最终答复")).not.toBeInTheDocument();
    },
  );
  it.each([404, 503])(
    "reports actual %s rather than fake empty actions",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(json({ error: { message: "failure" } }, status)),
      );
      render(<AgentActions {...props} />);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        String(status),
      );
      expect(screen.queryByTestId("agent-legacy")).not.toBeInTheDocument();
      expect(
        screen.queryByTestId("agent-not-committed"),
      ).not.toBeInTheDocument();
    },
  );
  it("does not show committed actions until SQL success and result reference are confirmed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(committed)));
    render(
      <AgentActions
        {...props}
        task={{ ...task, status: "running", result_available: false }}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "尚未确认成功提交",
    );
    expect(screen.queryByTestId("agent-step")).not.toBeInTheDocument();
  });
  it("rejects a committed action belonging to a different task", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json({
          ...committed,
          items: [{ ...committed.items[0], task_id: "other" }],
        }),
      ),
    );
    render(<AgentActions {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "不符合当前任务",
    );
  });
  it("does not infer live execution from model_mode alone", () => {
    expect(controllerLabel(undefined, undefined)).toContain("未知");
    expect(controllerLabel("single_agent", "live_llm")).toContain(
      "真实模型控制器",
    );
    expect(
      controllerLabel("legacy_single_call", "legacy_live_single_call"),
    ).toContain("不是 Agent");
  });
  it("limits large structured display without exposing hidden fields", () => {
    expect(
      publicText({ reasoning: "secret", result: "x".repeat(8000) }).length,
    ).toBeLessThan(6100);
    expect(publicText({ thought: "secret" })).not.toContain("secret");
  });
});
describe("action request lifecycle", () => {
  it("ignores an old action response after selecting a newer task", async () => {
    let resolveOld: (r: Response) => void = () => {};
    let oldSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, options: RequestInit) => {
        if (path.includes("/a/")) {
          oldSignal = options.signal as AbortSignal;
          return new Promise<Response>((r) => {
            resolveOld = r;
          });
        }
        return Promise.resolve(
          json({
            availability: "legacy",
            items: [],
            execution_kind: "legacy_single_call",
            controller_mode: "legacy_deterministic_echo",
          }),
        );
      }),
    );
    const { rerender } = render(<AgentActions {...props} />);
    await waitFor(() => expect(oldSignal).toBeDefined());
    rerender(<AgentActions {...props} task={{ ...task, id: "b" }} />);
    await screen.findByTestId("agent-legacy");
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => resolveOld(json(committed)));
    expect(screen.getByTestId("agent-legacy")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-step")).not.toBeInTheDocument();
  });
  it("aborts on pause and does not publish a late unauthorized error", async () => {
    let resolveOld: (r: Response) => void = () => {};
    let signal: AbortSignal | undefined;
    const unauthorized = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, options: RequestInit) => {
        signal = options.signal as AbortSignal;
        return new Promise<Response>((r) => {
          resolveOld = r;
        });
      }),
    );
    const { rerender, unmount } = render(
      <AgentActions {...props} onUnauthorized={unauthorized} />,
    );
    await waitFor(() => expect(signal).toBeDefined());
    rerender(
      <AgentActions {...props} polling={false} onUnauthorized={unauthorized} />,
    );
    expect(signal?.aborted).toBe(true);
    expect(
      screen.queryByText("正在读取已提交的 Agent 动作…"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("自动刷新已暂停；恢复后读取动作。"),
    ).toBeInTheDocument();
    unmount();
    await act(async () => resolveOld(json({}, 401)));
    expect(unauthorized).not.toHaveBeenCalled();
  });
  it("reports a current 401 with its captured identity epoch", async () => {
    const unauthorized = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    render(
      <AgentActions
        {...props}
        sessionEpoch={9}
        onUnauthorized={unauthorized}
      />,
    );
    await waitFor(() => expect(unauthorized).toHaveBeenCalledWith(9));
  });
  it("retries a failed action read explicitly without modifying task state", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json({}, 503))
      .mockResolvedValueOnce(json(committed));
    vi.stubGlobal("fetch", fetcher);
    render(<AgentActions {...props} />);
    await screen.findByRole("alert");
    fireEvent.click(
      screen.getByRole("button", { name: "重新读取 Agent 动作" }),
    );
    await screen.findByText("公开最终答复");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
