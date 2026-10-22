import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import {
  registerNavigationBlocker,
  useConsoleNavigation,
  useNavigationGuard,
} from "./navigation";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  dirty?: boolean;
  busy?: boolean;
  wide?: boolean;
  closeLabel?: string;
};
const focusable =
  'a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
export default function ConsoleDrawer({
  open,
  title,
  onClose,
  children,
  dirty = false,
  busy = false,
  wide = false,
  closeLabel = "关闭抽屉",
}: Props) {
  useConsoleNavigation();
  const titleId = useId(),
    confirmationId = useId();
  const dialog = useRef<HTMLDivElement>(null),
    layer = useRef<HTMLDivElement>(null);
  const [pending, setPending] = useState<(() => void) | null>(null);
  const pendingFocus = useRef<HTMLElement | null>(null);
  const requestLeave = useNavigationGuard();
  const close = useRef(onClose);
  close.current = onClose;
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  useLayoutEffect(() => {
    if (!open || (!dirty && !busy)) return;
    return registerNavigationBlocker({
      request: (action) => {
        if (!pendingRef.current)
          pendingFocus.current = document.activeElement as HTMLElement;
        setPending(() => action);
      },
    });
  }, [open, dirty, busy]);
  useEffect(() => {
    if (!open) setPending(null);
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement;
    const background = Array.from(document.body.children).filter(
      (node) => node !== layer.current,
    ) as HTMLElement[];
    const previous = background.map((node) => ({
      node,
      inert: node.inert,
      hidden: node.getAttribute("aria-hidden"),
    }));
    previous.forEach(({ node }) => {
      node.inert = true;
      node.setAttribute("aria-hidden", "true");
    });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const controls = () =>
      Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(focusable) || [],
      ).filter(
        (el) =>
          !el.closest("[hidden], [inert]") &&
          !Array.from(el.closest("details:not([open])")?.children || []).some(
            (child) => child.tagName !== "SUMMARY" && child.contains(el),
          ),
      );
    controls()[0]?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (pendingRef.current) {
          setPending(null);
          requestAnimationFrame(() => pendingFocus.current?.focus());
        } else requestLeave(() => close.current());
      }
      if (event.key === "Tab") {
        const items = controls(),
          first = items[0],
          last = items[items.length - 1];
        if (!first) {
          event.preventDefault();
          dialog.current?.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first ||
            !dialog.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            !dialog.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    const focusin = (event: FocusEvent) => {
      if (!dialog.current?.contains(event.target as Node))
        controls()[0]?.focus();
    };
    document.addEventListener("keydown", keydown);
    document.addEventListener("focusin", focusin);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("focusin", focusin);
      document.body.style.overflow = overflow;
      previous.forEach(({ node, inert, hidden }) => {
        node.inert = inert;
        if (hidden === null) node.removeAttribute("aria-hidden");
        else node.setAttribute("aria-hidden", hidden);
      });
      if (opener?.isConnected && !opener.closest("[inert]")) opener.focus();
      else document.querySelector<HTMLElement>("main")?.focus();
    };
  }, [open]);
  useLayoutEffect(() => {
    if (pending)
      dialog.current
        ?.querySelector<HTMLElement>('[role="alertdialog"] button')
        ?.focus();
  }, [pending]);
  // Saving can replace the editor without closing the drawer. Repair focus only
  // when its old control disappeared, never on ordinary field or polling updates.
  useLayoutEffect(() => {
    if (
      open &&
      dialog.current &&
      !dialog.current.contains(document.activeElement)
    ) {
      dialog.current
        .querySelector<HTMLElement>(
          pending
            ? '[role="alertdialog"] button'
            : ".console-drawer-header button",
        )
        ?.focus();
    }
  }, [open, title, pending]);
  if (!open) return null;
  return createPortal(
    <div
      className="console-overlay"
      ref={layer}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending)
          requestLeave(onClose);
      }}
    >
      <div
        className={`console-drawer ${wide ? "console-drawer-wide" : ""}`}
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="console-drawer-header" hidden={!!pending}>
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label={closeLabel}
            onClick={() => requestLeave(onClose)}
          >
            <X size={19} />
          </button>
        </header>
        <div className="console-drawer-body" hidden={!!pending}>
          {children}
        </div>
        {pending && (
          <div
            className="console-draft-confirm"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={confirmationId}
          >
            <h3 id={confirmationId}>
              {busy ? "请求仍在处理中" : "放弃未提交的草稿？"}
            </h3>
            <p>
              {busy
                ? "请求可能已到达服务端。离开只关闭当前视图，不会撤销操作；请稍后重新读取确认结果。"
                : "仅放弃当前本地草稿；不会撤销服务端可能已收到的操作。结果不确定时，请重新读取确认。"}
            </p>
            <div className="console-actions">
              <button
                type="button"
                onClick={() => {
                  setPending(null);
                  requestAnimationFrame(() => pendingFocus.current?.focus());
                }}
              >
                {busy ? "留在此页" : "继续编辑"}
              </button>
              <button
                type="button"
                className="danger"
                onClick={() => {
                  const action = pending;
                  setPending(null);
                  action();
                }}
              >
                {busy ? "仍然离开" : "放弃草稿"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
