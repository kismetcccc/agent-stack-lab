// Network-stub UI regressions only; these are not real Redis integration evidence.
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
import RedisLab from "./RedisLab";
import { request } from "./api";
import type { LabWrite, RedisSnapshot } from "./lab";

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const snapshot = (key: string, exists = true): RedisSnapshot => ({
  key,
  exists,
  value: exists ? `server-${key}` : null,
  ttl_ms: exists ? 60_000 : -2,
  observed_at: "2026-10-22T00:00:00Z",
});
const write: LabWrite = (path, options) => request(path, options);
function renderWorkspace() {
  return render(<RedisLab write={write} onUnauthorized={vi.fn()} />);
}
function input(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
function startDraft(key: string) {
  fireEvent.click(screen.getByRole("button", { name: "写入键值" }));
  input("键名", key);
  input("值", "draft value");
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  history.replaceState(null, "", "/");
});

describe("Redis workspace interruptions", () => {
  it("retains the exact attempted key after an uncertain write closes, without retrying or claiming rollback", async () => {
    const fetcher = vi.fn((_path: string, options?: RequestInit) =>
      options?.method === "PUT"
        ? Promise.reject(new TypeError("network interrupted"))
        : Promise.resolve(json(snapshot("uncertain-key", false))),
    );
    vi.stubGlobal("fetch", fetcher);
    renderWorkspace();
    startDraft("uncertain-key");
    fireEvent.click(screen.getByRole("button", { name: "写入并设置 TTL" }));
    await screen.findByText(/写入未获确认/);
    expect(screen.getByLabelText("键名")).toHaveValue("uncertain-key");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("查询键名")).toHaveValue("uncertain-key");
    expect(screen.getByRole("status")).toHaveTextContent("关闭不会撤销写入");
    expect(
      screen.queryByText(/已撤销|已回滚|取消成功/),
    ).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);

    // An explicit fact check is a GET of the retained key, never another PUT.
    fireEvent.click(screen.getByRole("button", { name: "读取键值" }));
    await screen.findByText("服务端确认：键不存在");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "PUT"),
    ).toHaveLength(1);
    expect(fetcher.mock.calls[1][0]).toBe(
      "/api/v1/lab/redis/keys/uncertain-key",
    );
  });

  it("invalidates a busy drawer response so a late PUT cannot overwrite a newer key query", async () => {
    let resolveWrite: (response: Response) => void = () => {};
    let writeSignal: AbortSignal | undefined;
    const fetcher = vi.fn((_path: string, options?: RequestInit) => {
      if (options?.method === "PUT") {
        writeSignal = options.signal as AbortSignal;
        // Deliberately ignore abort in this stub to test the stale-response guard.
        return new Promise<Response>((resolve) => {
          resolveWrite = resolve;
        });
      }
      return Promise.resolve(json(snapshot("new-key")));
    });
    vi.stubGlobal("fetch", fetcher);
    renderWorkspace();
    startDraft("old-key");
    fireEvent.click(screen.getByRole("button", { name: "写入并设置 TTL" }));
    expect(writeSignal?.aborted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(confirmation).toHaveTextContent("不会撤销操作");
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "仍然离开" }),
    );
    expect(writeSignal?.aborted).toBe(true);
    expect(screen.getByLabelText("查询键名")).toHaveValue("old-key");

    input("查询键名", "new-key");
    fireEvent.click(screen.getByRole("button", { name: "读取键值" }));
    await waitFor(() =>
      expect(screen.getByTestId("redis-observation")).toHaveAttribute(
        "data-key",
        "new-key",
      ),
    );
    await act(async () => resolveWrite(json(snapshot("old-key"))));
    expect(screen.getByTestId("redis-observation")).toHaveAttribute(
      "data-key",
      "new-key",
    );
    expect(screen.getByLabelText("查询键名")).toHaveValue("new-key");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText(/写入后已从服务端回读/)).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "PUT"),
    ).toHaveLength(1);
  });

  it("keeps dirty inputs when closing is canceled and discards only after confirmation, without writes", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    renderWorkspace();
    startDraft("draft-key");
    input("过期时间（秒）", "45");
    fireEvent.keyDown(document, { key: "Escape" });
    const confirmation = screen.getByRole("alertdialog");
    expect(confirmation).toHaveTextContent("仅放弃当前本地草稿");
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "继续编辑" }),
    );
    expect(screen.getByLabelText("键名")).toHaveValue("draft-key");
    expect(screen.getByLabelText("值")).toHaveValue("draft value");
    expect(screen.getByLabelText("过期时间（秒）")).toHaveValue(45);
    expect(fetcher).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("confirms the explicit snapshot key, sends one DELETE, and keeps delete acknowledgment separate from readback", async () => {
    let resolveDelete: (response: Response) => void = () => {};
    let reads = 0;
    const fetcher = vi.fn((_path: string, options?: RequestInit) => {
      if (options?.method === "DELETE")
        return new Promise<Response>((resolve) => {
          resolveDelete = resolve;
        });
      return Promise.resolve(json(snapshot("delete-key", reads++ === 0)));
    });
    vi.stubGlobal("fetch", fetcher);
    renderWorkspace();
    input("查询键名", "delete-key");
    fireEvent.click(screen.getByRole("button", { name: "读取键值" }));
    await screen.findByText("服务端确认：键存在");
    fireEvent.click(screen.getByRole("button", { name: "删除键" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("delete-key");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("redis-observation")).toHaveAttribute(
      "data-key",
      "delete-key",
    );

    fireEvent.click(screen.getByRole("button", { name: "删除键" }));
    const confirmButton = screen.getByRole("button", { name: "确认删除" });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "DELETE"),
    ).toHaveLength(1);
    expect(fetcher.mock.calls[1][0]).toBe(
      "/api/v1/lab/redis/keys/delete-key?confirm=true",
    );
    await act(async () => resolveDelete(json(null, 204)));
    expect(screen.getByRole("status")).toHaveTextContent(
      "删除响应不代替再次读取",
    );
    expect(screen.queryByText("服务端确认：键不存在")).not.toBeInTheDocument();
    expect(reads).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "读取键值" }));
    await screen.findByText("服务端确认：键不存在");
    expect(reads).toBe(2);
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "DELETE"),
    ).toHaveLength(1);
  });
});
