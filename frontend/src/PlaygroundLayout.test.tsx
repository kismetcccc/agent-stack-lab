// DOM namespace regression only. Pixel geometry and responsive screenshots are
// checked in real-browser CI, not inferred from jsdom's non-layout rendering.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import ComponentPlayground from "./ComponentPlayground";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("isolated playground layout", () => {
  it.each(["mysql", "mongo", "redis", "kafka"])(
    "%s uses an isolated workbench grid, not legacy architecture columns",
    async (component) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockImplementation(() =>
            Promise.resolve(
              new Response(
                JSON.stringify({ items: [], total: 0, limit: 10, offset: 0 }),
                { headers: { "Content-Type": "application/json" } },
              ),
            ),
          ),
      );
      render(
        <ComponentPlayground
          component={component}
          authenticated
          authPanel={null}
          mode="production"
          write={async () => {
            throw new Error("No writes in CSS test");
          }}
          onUnauthorized={() => {}}
        />,
      );
      const workspace = screen.getByTestId(`component-${component}`);
      const grid = workspace.querySelector<HTMLElement>(".lab-workbench-grid")!;
      expect(grid).not.toBeNull();
      expect(workspace.querySelector(".component-grid")).toBeNull();
      expect(grid.querySelector(":scope > .lab-editor")).not.toBeNull();
      expect(grid.querySelector(":scope > .lab-results")).not.toBeNull();
      if (component !== "redis")
        await screen.findByText(
          component === "kafka" ? /还没有消息记录/ : /还没有(文档|记录)/,
        );
    },
  );
});
