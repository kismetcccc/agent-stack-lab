import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import PlaygroundHome, { type Readiness } from "./PlaygroundHome";
afterEach(cleanup);
const base: Readiness = {
  data: {
    mode: "production",
    status: "ready",
    dependencies: { mysql: "up", mongo: "up", kafka: "up" },
  },
  receivedAt: "2026-10-22T09:00:00Z",
  httpStatus: 200,
  loading: false,
  error: "",
  stale: false,
};
describe("overview evidence, not inferred monitoring", () => {
  it("shows actual probes and never infers Redis or Worker readiness", () => {
    const refresh = vi.fn();
    render(<PlaygroundHome readiness={base} onRefresh={refresh} />);
    expect(screen.getAllByText("探测通过")).toHaveLength(3);
    expect(
      within(screen.getByTestId("resource-redis")).getByText("未提供总体探针"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/API 可响应不等于 Worker 正在工作/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("readiness-summary")).toHaveTextContent(
      "浏览器收取响应时间",
    );
    fireEvent.click(screen.getByRole("button", { name: "刷新检查" }));
    expect(refresh).toHaveBeenCalledOnce();
  });
  it("keeps fresh 503 dependency evidence instead of replacing it with unknown", () => {
    render(
      <PlaygroundHome
        readiness={{
          ...base,
          httpStatus: 503,
          data: {
            ...base.data,
            dependencies: { mysql: "up", mongo: "down", kafka: "up" },
          },
          error: "部分依赖未就绪",
        }}
        onRefresh={() => {}}
      />,
    );
    expect(
      within(screen.getByTestId("resource-mongo")).getByText("未就绪"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("readiness-summary")).toHaveTextContent(
      "HTTP 503",
    );
    expect(screen.queryByText("上次检查，非当前状态")).not.toBeInTheDocument();
  });
  it("labels retained snapshots stale after a failed request", () => {
    render(
      <PlaygroundHome
        readiness={{ ...base, stale: true, error: "当前服务状态未知" }}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getByText("上次检查，非当前状态")).toBeInTheDocument();
    expect(screen.getByText("当前服务状态未知")).toBeInTheDocument();
  });
  it("missing fields remain unknown even with production or HTTP 200", () => {
    render(
      <PlaygroundHome
        readiness={{ ...base, data: { mode: "production" } }}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getAllByText("未知 / 未取得")).toHaveLength(3);
    expect(screen.queryByText("探测通过")).not.toBeInTheDocument();
  });
  it("marks SQLite and in-memory adapters explicitly as substitutes", () => {
    render(
      <PlaygroundHome
        readiness={{
          ...base,
          data: {
            mode: "demo",
            dependencies: {
              sqlite: "up",
              mongo: "in_memory_test_adapter",
              kafka: "in_memory_test_adapter",
            },
          },
        }}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getByText("SQLite 替代 · 非 MySQL")).toBeInTheDocument();
    expect(screen.getAllByText("测试替身")).toHaveLength(2);
    expect(screen.queryByText("探测通过")).not.toBeInTheDocument();
  });
  it("distinguishes first loading from no valid response", () => {
    const view = render(
      <PlaygroundHome
        readiness={{
          ...base,
          data: null,
          receivedAt: null,
          httpStatus: null,
          loading: true,
        }}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getByText("正在读取 /readyz")).toBeInTheDocument();
    view.rerender(
      <PlaygroundHome
        readiness={{
          ...base,
          data: null,
          receivedAt: null,
          httpStatus: null,
          error: "无法连接",
          loading: false,
        }}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getByText("状态未知 / 未取得")).toBeInTheDocument();
    expect(screen.queryByText(/HTTP 200/)).not.toBeInTheDocument();
  });
});
