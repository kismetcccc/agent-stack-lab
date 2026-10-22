// DOM structure regression only. Real geometry/screenshots are checked in browser CI.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import ComponentPlayground from "./ComponentPlayground";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

describe("list-first resource workspaces", () => {
  it.each(["mysql", "mongo", "redis", "kafka"])(
    "%s keeps editors closed and data primary",
    async (component) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
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
            throw new Error("No writes in layout test");
          }}
          onUnauthorized={() => {}}
        />,
      );
      const workspace = screen.getByTestId(`component-${component}`);
      expect(workspace.querySelector(".lab-resource-workspace")).not.toBeNull();
      expect(screen.getByTestId("resource-primary")).toBeInTheDocument();
      expect(
        workspace.querySelector(".component-grid, .lab-workbench-grid"),
      ).toBeNull();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(workspace.querySelector(".lab-editor")).toBeNull();
      if (component !== "redis")
        await screen.findByText(
          component === "kafka" ? /还没有消息记录/ : /还没有(文档|记录)/,
        );
      fireEvent.click(screen.getByRole("button", { name: "帮助" }));
      expect(screen.getByRole("dialog")).toHaveTextContent("安全边界");
      expect(screen.getByRole("dialog")).toHaveTextContent("字段限制");
    },
  );
});
