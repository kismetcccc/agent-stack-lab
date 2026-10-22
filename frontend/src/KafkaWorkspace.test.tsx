// Network-stub UI regressions only; these do not claim real Kafka integration.
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
import KafkaLab from "./KafkaLab";
import { request } from "./api";
import type { KafkaMessage, LabWrite } from "./lab";

const firstId = "00000000-0000-4000-8000-000000000011";
const secondId = "00000000-0000-4000-8000-000000000022";
const timestamp = "2026-10-22T00:00:00Z";
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
const historyPage = () => json({ items: [], total: 0, limit: 10, offset: 0 });
const message = (id: string): KafkaMessage => ({
  id,
  key: `key-${id.slice(-2)}`,
  value: `registered-${id}`,
  topic: "agent.lab.messages.v1",
  created_at: timestamp,
  observed_at: timestamp,
  producer: {
    status: "unconfirmed",
    partition: null,
    offset: null,
    acknowledged_at: null,
  },
  consumer: {
    status: "received",
    key: `received-${id.slice(-2)}`,
    value: `actual-${id}`,
    group: "agent-lab-observer-v1",
    partition: 2,
    offset: 8,
    received_at: timestamp,
  },
});
const write: LabWrite = (path, options) => request(path, options);
const props = { write, onUnauthorized: vi.fn() };

function selectMessage(id: string) {
  const oldURL = location.href;
  history.pushState(null, "", `/#kafka?message=${id}`);
  window.dispatchEvent(
    new HashChangeEvent("hashchange", { oldURL, newURL: location.href }),
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  history.replaceState(null, "", "/");
});

describe("Kafka drawer interruption regressions", () => {
  it("aborts a stalled detail GET at 20 seconds and pauses honestly without sending", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    history.replaceState(null, "", `/#kafka?message=${firstId}`);
    let signal: AbortSignal | undefined;
    let finish: (response: Response) => void = () => {};
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (path.includes("?")) return Promise.resolve(historyPage());
      signal = options?.signal as AbortSignal;
      // Deliberately ignore abort so a late transport resolution is exercised.
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    });
    vi.stubGlobal("fetch", fetcher);
    await act(async () => {
      render(<KafkaLab {...props} />);
    });
    expect(signal).toBeDefined();
    expect(signal?.aborted).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(signal?.aborted).toBe(true);
    expect(screen.getByText(/自动观察已暂停，可手动刷新/)).toHaveTextContent(
      "尚未观察到不代表发送失败",
    );
    expect(screen.getByText(/尚未取得消息记录/)).toBeInTheDocument();
    await act(async () => {
      finish(json(message(firstId)));
    });
    expect(screen.queryByTestId("kafka-detail")).not.toBeInTheDocument();
    const calls = fetcher.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(40000);
    });
    expect(fetcher).toHaveBeenCalledTimes(calls);
    expect(
      fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(false);
  });

  it("ignores a late A response after selecting B and a late B refresh after closing", async () => {
    history.replaceState(null, "", `/#kafka?message=${firstId}`);
    const pending = new Map<
      string,
      { signal: AbortSignal; finish: (response: Response) => void }
    >();
    let secondReads = 0;
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (path.includes("?")) return Promise.resolve(historyPage());
      if (path.endsWith(secondId) && ++secondReads === 1)
        return Promise.resolve(json(message(secondId)));
      return new Promise<Response>((finish) => {
        pending.set(path.endsWith(firstId) ? "first" : "refresh", {
          signal: options?.signal as AbortSignal,
          finish,
        });
      });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<KafkaLab {...props} />);
    await waitFor(() => expect(pending.has("first")).toBe(true));
    await act(async () => selectMessage(secondId));
    await waitFor(() =>
      expect(pending.get("first")?.signal.aborted).toBe(true),
    );
    expect(await screen.findByTestId("kafka-detail")).toHaveAttribute(
      "data-message-id",
      secondId,
    );
    await act(async () => pending.get("first")?.finish(json(message(firstId))));
    expect(screen.getByTestId("kafka-detail")).toHaveAttribute(
      "data-message-id",
      secondId,
    );
    expect(screen.getByTestId("kafka-consumer-value")).toHaveTextContent(
      `actual-${secondId}`,
    );
    expect(screen.queryByText(`actual-${firstId}`)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "手动刷新" }));
    await waitFor(() => expect(pending.has("refresh")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
    expect(pending.get("refresh")?.signal.aborted).toBe(true);
    expect(location.hash).toBe("#kafka");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () =>
      pending.get("refresh")?.finish(json(message(secondId))),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kafka-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("resource-primary")).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(false);
  });

  it("keeps a dirty composer and its focus on continue, then discards without a POST", async () => {
    history.replaceState(null, "", "/#kafka");
    const fetcher = vi.fn((_path: string, _options?: RequestInit) =>
      Promise.resolve(historyPage()),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<KafkaLab {...props} />);
    await screen.findByText(/还没有消息记录/);
    const opener = screen.getByRole("button", { name: "发送消息" });
    opener.focus();
    fireEvent.click(opener);
    const draft = screen.getByLabelText("消息内容");
    fireEvent.change(screen.getByLabelText("消息键"), {
      target: { value: "unsent-key" },
    });
    fireEvent.change(draft, { target: { value: "keep this unsent draft" } });
    draft.focus();
    fireEvent.keyDown(draft, { key: "Escape" });
    const confirmation = screen.getByRole("alertdialog");
    expect(
      within(confirmation).getByRole("button", { name: "继续编辑" }),
    ).toHaveFocus();
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "继续编辑" }),
    );
    await waitFor(() => expect(draft).toHaveFocus());
    expect(screen.getByLabelText("消息键")).toHaveValue("unsent-key");
    expect(draft).toHaveValue("keep this unsent draft");
    fireEvent.keyDown(draft, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(
      fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(false);
    fireEvent.click(opener);
    expect(screen.getByLabelText("消息键")).toHaveValue("");
    expect(screen.getByLabelText("消息内容")).toHaveValue("");
  });
});
