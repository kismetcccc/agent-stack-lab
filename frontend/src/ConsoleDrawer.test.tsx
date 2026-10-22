import { useState } from "react";
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
import ConsoleDrawer from "./ConsoleDrawer";
import {
  commitHash,
  useConsoleNavigation,
  useNavigationGuard,
} from "./navigation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "#mysql");
});
function Harness({ busy = false }: { busy?: boolean }) {
  useConsoleNavigation();
  const [open, setOpen] = useState(false),
    [draft, setDraft] = useState("");
  const guard = useNavigationGuard();
  return (
    <>
      <button onClick={() => setOpen(true)}>打开编辑</button>
      <a href="#redis">其他页面</a>
      <main tabIndex={-1} />
      <ConsoleDrawer
        open={open}
        title="编辑记录"
        dirty={!!draft}
        busy={busy}
        onClose={() => {
          setOpen(false);
          setDraft("");
        }}
      >
        <label>
          名称
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>
        <button onClick={() => guard(() => setDraft("另一对象"))}>
          选择另一对象
        </button>
        <details>
          <summary>响应详情</summary>
          <pre tabIndex={0}>closed response</pre>
        </details>
      </ConsoleDrawer>
    </>
  );
}
function open() {
  const button = screen.getByRole("button", { name: "打开编辑" });
  button.focus();
  fireEvent.click(button);
  return button;
}
describe("shared accessible console drawer", () => {
  it("traps visible controls only and restores the launcher on Escape", () => {
    render(<Harness />);
    const launcher = open();
    const close = screen.getByRole("button", { name: "关闭抽屉" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByText("响应详情")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(launcher).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });
  it("keeps dirty input until discard, without claiming a delivered write was undone", async () => {
    render(<Harness />);
    open();
    const input = screen.getByLabelText("名称");
    fireEvent.change(input, { target: { value: "草稿" } });
    input.focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.getByRole("alertdialog", { name: "放弃未提交的草稿？" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/不会撤销服务端可能已收到的操作/),
    ).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveValue("草稿");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(input).toHaveValue("草稿");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    open();
    expect(screen.getByLabelText("名称")).toHaveValue("");
  });
  it("guards newer object selections through the same prompt", () => {
    render(<Harness />);
    open();
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "旧草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "选择另一对象" }));
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("名称")).toHaveValue("旧草稿");
    fireEvent.click(screen.getByRole("button", { name: "选择另一对象" }));
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(screen.getByLabelText("名称")).toHaveValue("另一对象");
  });
  it("warns that closing a pending request does not cancel the server operation", () => {
    render(<Harness busy />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(
      screen.getByRole("alertdialog", { name: "请求仍在处理中" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/不会撤销操作/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "留在此页" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "仍然离开" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("blocks unload while a draft exists and removes that guard after unmount", () => {
    const view = render(<Harness />);
    open();
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "draft" },
    });
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    view.unmount();
    const next = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(next);
    expect(next.defaultPrevented).toBe(false);
  });
  it("rewinds blocked hash changes and preserves Back/Forward after discard", async () => {
    history.replaceState(null, "", "#mysql");
    render(<Harness />);
    act(() => commitHash("mongo"));
    expect(location.hash).toBe("#mongo");
    open();
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "draft" },
    });
    act(() => history.back());
    await screen.findByRole("alertdialog");
    await waitFor(() => expect(location.hash).toBe("#mongo"));
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("名称")).toHaveValue("draft");
    act(() => history.back());
    await screen.findByRole("alertdialog");
    await waitFor(() => expect(location.hash).toBe("#mongo"));
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    await waitFor(() => expect(location.hash).toBe("#mysql"));
    // Mimic the route unmount that occurs in App; history entry itself is intact.
    cleanup();
    act(() => history.forward());
    await waitFor(() => expect(location.hash).toBe("#mongo"));
  });
});

it("keeps the latest rapid native hash intent and all intermediate history entries", async () => {
  history.replaceState(null, "", "#a");
  render(<Harness />);
  act(() => {
    commitHash("b");
    commitHash("c");
  });
  open();
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "draft" },
  });
  act(() => {
    location.hash = "#d";
    location.hash = "#e";
  });
  await screen.findByRole("alertdialog");
  await waitFor(() => expect(location.hash).toBe("#c"));
  fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByLabelText("名称")).toHaveValue("draft");
  // The first burst is still in Forward history, not overwritten by cancellation.
  act(() => history.go(2));
  await screen.findByRole("alertdialog");
  await waitFor(() => expect(location.hash).toBe("#c"));
  fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
  await waitFor(() => expect(location.hash).toBe("#e"));
  cleanup();
  act(() => history.back());
  await waitFor(() => expect(location.hash).toBe("#d"));
  act(() => history.back());
  await waitFor(() => expect(location.hash).toBe("#c"));
  act(() => history.go(2));
  await waitFor(() => expect(location.hash).toBe("#e"));
});

it("accepts the last of two native hashes directly from the first draft prompt", async () => {
  history.replaceState(null, "", "#a");
  render(<Harness />);
  act(() => {
    commitHash("b");
    commitHash("c");
  });
  open();
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "draft" },
  });
  act(() => {
    location.hash = "#d";
    location.hash = "#e";
  });
  await screen.findByRole("alertdialog");
  await waitFor(() => expect(location.hash).toBe("#c"));
  fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
  await waitFor(() => expect(location.hash).toBe("#e"));
});

it("indexes a clean native burst before a later dirty Back into its intermediate entry", async () => {
  history.replaceState(null, "", "#a");
  render(<Harness />);
  act(() => {
    commitHash("b");
    commitHash("c");
  });
  const published: string[] = [];
  const listener = () => published.push(location.hash);
  window.addEventListener("hashchange", listener);
  act(() => {
    location.hash = "#d";
    location.hash = "#e";
  });
  await waitFor(() => expect(published).toEqual(["#e"]));
  open();
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "draft" },
  });
  act(() => history.back());
  await screen.findByRole("alertdialog");
  await waitFor(() => expect(location.hash).toBe("#e"));
  fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
  await waitFor(() => expect(location.hash).toBe("#d"));
  window.removeEventListener("hashchange", listener);
});

it("does not stop a burst rewind at a different entry with the same URL", async () => {
  history.replaceState(null, "", "#a");
  render(<Harness />);
  act(() => {
    commitHash("b");
    commitHash("c");
  });
  open();
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "draft" },
  });
  const initial = history.state.stackLabPosition;
  act(() => {
    location.hash = "#d";
    location.hash = "#c";
    location.hash = "#e";
  });
  await screen.findByRole("alertdialog");
  await waitFor(() => {
    expect(location.hash).toBe("#c");
    expect(history.state.stackLabPosition).toBe(initial);
  });
  fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
  await waitFor(() => expect(location.hash).toBe("#e"));
  cleanup();
  act(() => history.back());
  await waitFor(() => {
    expect(location.hash).toBe("#c");
    expect(history.state.stackLabPosition).toBe(initial + 2);
  });
});

it("indexes clean bursts returning to the same URL before blocking a later Back", async () => {
  history.replaceState(null, "", "#a");
  render(<Harness />);
  act(() => {
    commitHash("b");
    commitHash("c");
  });
  const initial = history.state.stackLabPosition;
  const published: number[] = [];
  const listener = () => published.push(history.state.stackLabPosition);
  window.addEventListener("hashchange", listener);
  act(() => {
    location.hash = "#d";
    location.hash = "#c";
  });
  await waitFor(() => expect(published).toEqual([initial + 2]));
  open();
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "draft" },
  });
  act(() => history.back());
  await screen.findByRole("alertdialog");
  await waitFor(() => expect(history.state.stackLabPosition).toBe(initial + 2));
  fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(location.hash).toBe("#c");
  expect(history.state.stackLabPosition).toBe(initial + 2);
  window.removeEventListener("hashchange", listener);
});

it("tracks same-URL history traversals without dropping the draft or corrupting the next Back", async () => {
  history.replaceState(null, "", "#a");
  render(<Harness />);
  act(() => {
    commitHash("c");
    commitHash("d");
    commitHash("c");
  });
  const last = history.state.stackLabPosition;
  open();
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "draft" },
  });
  act(() => history.go(-2));
  await waitFor(() => expect(history.state.stackLabPosition).toBe(last - 2));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("名称")).toHaveValue("draft");
  act(() => history.back());
  await screen.findByRole("alertdialog");
  await waitFor(() => {
    expect(location.hash).toBe("#c");
    expect(history.state.stackLabPosition).toBe(last - 2);
  });
  fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
  await waitFor(() => expect(location.hash).toBe("#a"));
});

it.each([false, true])(
  "coalesces repeated queued target URLs (dirty=%s) without corrupting history",
  async (dirty) => {
    history.replaceState(null, "", "#a");
    render(<Harness />);
    act(() => {
      commitHash("b");
      commitHash("c");
    });
    const initial = history.state.stackLabPosition;
    if (dirty) {
      open();
      fireEvent.change(screen.getByLabelText("名称"), {
        target: { value: "draft" },
      });
    }
    const published: number[] = [];
    const listener = () => published.push(history.state.stackLabPosition);
    window.addEventListener("hashchange", listener);
    act(() => {
      location.hash = "#d";
      location.hash = "#c";
      location.hash = "#d";
      location.hash = "#c";
    });
    await waitFor(() => expect(published).toEqual([initial + 4]));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    if (!dirty) {
      open();
      fireEvent.change(screen.getByLabelText("名称"), {
        target: { value: "draft" },
      });
    }
    act(() => history.back());
    await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(history.state.stackLabPosition).toBe(initial + 4),
    );
    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    await waitFor(() => expect(location.hash).toBe("#d"));
    window.removeEventListener("hashchange", listener);
  },
);
