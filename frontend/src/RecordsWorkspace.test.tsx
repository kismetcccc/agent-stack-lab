// Network-stub regression tests, not evidence of a real MySQL/Mongo integration.
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
import { request } from "./api";
import type { LabWrite } from "./lab";

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const id = "00000000-0000-4000-8000-000000000001";
const row = {
  id,
  name: "saved name",
  value: "saved value",
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
};
const page = (items: unknown[], total = items.length, offset = 0) => ({
  items,
  total,
  limit: 10,
  offset,
});
const write: LabWrite = (path, options) => request(path, options);
const props = { write, onUnauthorized: vi.fn() };
const input = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  history.replaceState(null, "", "/");
});

describe("record workspace interruptions", () => {
  it("protects a real draft on Escape, restores focus, and only discards after confirmation", async () => {
    const fetcher = vi.fn(() => Promise.resolve(json(page([]))));
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText(/还没有记录/);
    const opener = screen.getByRole("button", { name: "新建记录" });
    opener.focus();
    fireEvent.click(opener);
    input("名称", "keep me");
    const name = screen.getByLabelText("名称");
    name.focus();
    fireEvent.keyDown(name, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "放弃未提交的草稿",
    );
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    await waitFor(() => expect(name).toHaveFocus());
    expect(name).toHaveValue("keep me");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("invalidates a closed pending write so its late response cannot replace a newer draft", async () => {
    let finish: (response: Response) => void = () => {};
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn((_path: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        signal = options.signal as AbortSignal;
        return new Promise<Response>((resolve) => {
          finish = resolve;
        });
      }
      return Promise.resolve(json(page([])));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText(/还没有记录/);
    fireEvent.click(screen.getByRole("button", { name: "新建记录" }));
    input("名称", "first request");
    fireEvent.click(screen.getByRole("button", { name: "创建记录" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("不会撤销操作");
    fireEvent.click(screen.getByRole("button", { name: "仍然离开" }));
    expect(signal?.aborted).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "新建记录" }));
    input("名称", "new local draft");
    await act(async () => finish(json(row, 201)));
    expect(
      screen.getByRole("dialog", { name: "新建记录" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("名称")).toHaveValue("new local draft");
    expect(screen.queryByText(/服务端已保存/)).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "POST"),
    ).toHaveLength(1);
  });

  it("separates an acknowledged write from a failed list reread", async () => {
    let saved = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, options?: RequestInit) => {
        if (options?.method === "POST") {
          saved = true;
          return Promise.resolve(json(row, 201));
        }
        return Promise.resolve(
          saved
            ? json(
                {
                  error: { message: "list unavailable" },
                  request_id: "readback-failure",
                },
                503,
              )
            : json(page([])),
        );
      }),
    );
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText(/还没有记录/);
    fireEvent.click(screen.getByRole("button", { name: "新建记录" }));
    input("名称", "request name");
    fireEvent.click(screen.getByRole("button", { name: "创建记录" }));
    const detail = await screen.findByRole("dialog", { name: "记录详情" });
    await waitFor(() =>
      expect(within(detail).getByRole("alert")).toHaveTextContent(
        "readback-failure",
      ),
    );
    expect(detail).toHaveTextContent("saved value");
    expect(detail).toHaveTextContent("写入响应与列表回读是两步");
    expect(detail).toHaveTextContent("服务端已保存");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "当前保留上一次读取的内容，并非最新状态",
    );
  });

  it("keeps Mongo indexes compact and sends a full replacement without old fields", async () => {
    const document = {
      id,
      document: { old: "removed", keep: 1 },
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
    let updated = document;
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (options?.method === "PUT") {
        updated = {
          ...document,
          document: JSON.parse(String(options.body)).document,
        };
        return Promise.resolve(json(updated));
      }
      return Promise.resolve(
        json(path.includes("?") ? page([updated]) : updated),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mongo" {...props} />);
    fireEvent.click(
      await screen.findByRole("button", { name: `替换文档 ${id}` }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("JSON 文档")).toHaveValue(
        JSON.stringify(document.document, null, 2),
      ),
    );
    input("JSON 文档", '{"new":"only"}');
    expect(screen.getByText(/完整替换，不是字段合并/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    const detail = await screen.findByRole("dialog", { name: "文档详情" });
    expect(detail).toHaveTextContent('"new": "only"');
    expect(
      fetcher.mock.calls.find(([, options]) => options?.method === "PUT")?.[1]
        ?.body,
    ).toBe('{"document":{"new":"only"}}');
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(screen.getByRole("table")).toHaveTextContent("1 个顶层字段 · new");
    expect(screen.getByRole("table")).not.toHaveTextContent("only");
    expect(screen.getByRole("table").querySelector("pre")).toBeNull();
  });

  it("falls back from a deleted last page without losing the server total", async () => {
    const first = Array.from({ length: 10 }, (_, n) => ({
      ...row,
      id: `row-${n}`,
      name: `row ${n}`,
    }));
    let deleted = false;
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (options?.method === "DELETE") {
        deleted = true;
        return Promise.resolve(json(null, 204));
      }
      const offset = new URL(path, "http://local").searchParams.get("offset");
      return Promise.resolve(
        json(
          offset === "10"
            ? page(deleted ? [] : [row], deleted ? 10 : 11, 10)
            : page(first, deleted ? 10 : 11),
        ),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    await screen.findByText("共 11 条 · 每页 10 条");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "删除 saved name" }),
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(id);
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await screen.findByText("共 10 条 · 每页 10 条");
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByRole("table")).toHaveTextContent("row 0");
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "DELETE"),
    ).toHaveLength(1);
  });

  it("does not recreate a record deleted elsewhere between fresh read and update", async () => {
    let gone = false;
    const fetcher = vi.fn((path: string, options?: RequestInit) => {
      if (options?.method === "PUT") {
        gone = true;
        return Promise.resolve(json({ error: { message: "not found" } }, 404));
      }
      return Promise.resolve(
        json(path.includes("?") ? page(gone ? [] : [row]) : row),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<RecordsLab kind="mysql" {...props} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "编辑 saved name" }),
    );
    await screen.findByLabelText("名称");
    input("内容", "replacement");
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await screen.findByText(/这条教学数据已不存在/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "POST"),
    ).toHaveLength(0);
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "PUT"),
    ).toHaveLength(1);
  });
});
