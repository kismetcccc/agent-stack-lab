import { useLayoutEffect } from "react";

type Blocker = { request: (action: () => void) => void };
const positionKey = "stackLabPosition";
let users = 0;
let position = 0;
let currentURL = "";
let blocker: Blocker | null = null;
let restoring = false;
let restoreCursor: { position: number; direction: number } | null = null;
let afterRestore: (() => void) | null = null;
let allowedURL: string | null = null;
let publishing = false;
let batch: { oldURL: string; newURL: string }[] = [];
let batchTimer: ReturnType<typeof setTimeout> | undefined;

function stamp(index: number) {
  history.replaceState({ ...history.state, [positionKey]: index }, "");
}
function publish(oldURL: string, newURL: string) {
  publishing = true;
  try {
    window.dispatchEvent(new HashChangeEvent("hashchange", { oldURL, newURL }));
  } finally {
    publishing = false;
  }
}
function perform(action: () => void) {
  const before = location.href;
  action();
  if (location.href !== before && currentURL !== location.href)
    allowedURL = location.href;
}
function processNavigation(nativeEntries: number) {
  const targetURL = location.href;
  if (
    restoring &&
    targetURL === currentURL &&
    history.state?.[positionKey] === position
  ) {
    restoring = false;
    restoreCursor = null;
    const resume = afterRestore;
    afterRestore = null;
    resume?.();
    return;
  }
  if (restoring && restoreCursor) {
    restoreCursor.position += restoreCursor.direction;
    stamp(restoreCursor.position);
    history.go(restoreCursor.direction);
    return;
  }
  let targetPosition = history.state?.[positionKey];
  const unindexed = typeof targetPosition !== "number";
  if (unindexed) {
    targetPosition = position + Math.max(1, nativeEntries);
    stamp(targetPosition);
  }
  const burst = unindexed && nativeEntries > 1;
  if (
    targetURL === allowedURL ||
    (!blocker && !burst) ||
    (targetURL === currentURL && targetPosition === position)
  ) {
    const oldURL = currentURL;
    allowedURL = null;
    currentURL = targetURL;
    position = targetPosition;
    publish(oldURL, targetURL);
    return;
  }
  const delta = targetPosition - position;
  const resume = () => {
    allowedURL = targetURL;
    if (delta) history.go(delta);
    else {
      history.replaceState(history.state, "", targetURL);
      processNavigation(0);
    }
  };
  // Rewind the actual cursor, never overwrite an older URL. Stamp every skipped
  // native entry so later Back/Forward can distinguish repeated identical URLs.
  restoring = !!delta;
  restoreCursor =
    burst && delta
      ? { position: targetPosition, direction: -Math.sign(delta) }
      : null;
  if (delta) history.go(restoreCursor ? restoreCursor.direction : -delta);
  else history.replaceState(history.state, "", currentURL);
  const continueNavigation = () => {
    if (restoring) afterRestore = resume;
    else resume();
  };
  // Returning to the same resource does not discard its draft, but a native
  // burst still needs its intermediate history entries indexed.
  if (blocker && targetURL !== currentURL) blocker.request(continueNavigation);
  else continueNavigation();
}
function changed(event: HashChangeEvent) {
  if (publishing) return;
  event.stopImmediatePropagation();
  // Native events are queued. C→D→C→E may already be at E before the first
  // event runs, and C may occur more than once. Batch before touching history:
  // publish only the latest intent, while counting every actual native entry.
  if (event.newURL) {
    const last = batch[batch.length - 1];
    if (!last || last.oldURL !== event.oldURL || last.newURL !== event.newURL)
      batch.push({ oldURL: event.oldURL, newURL: event.newURL });
  }
  if (batchTimer === undefined)
    batchTimer = setTimeout(() => {
      const count = batch.length;
      batch = [];
      batchTimer = undefined;
      processNavigation(count);
    }, 0);
}
// Traversals between identical URLs emit only popstate. They preserve the draft,
// but the indexed cursor (and an accepted internal replay) must still advance.
function moved(event: PopStateEvent) {
  if (
    !restoring &&
    location.href === currentURL &&
    typeof event.state?.[positionKey] === "number"
  ) {
    position = event.state[positionKey];
    if (allowedURL === currentURL) {
      allowedURL = null;
      publish(currentURL, currentURL);
    }
  }
}
function unloading(event: BeforeUnloadEvent) {
  if (!blocker) return;
  event.preventDefault();
  event.returnValue = "";
}
export function useConsoleNavigation() {
  useLayoutEffect(() => {
    if (users++ === 0) {
      position =
        typeof history.state?.[positionKey] === "number"
          ? history.state[positionKey]
          : 0;
      currentURL = location.href;
      stamp(position);
      window.addEventListener("hashchange", changed, true);
      window.addEventListener("popstate", moved);
      window.addEventListener("beforeunload", unloading);
    }
    return () => {
      if (--users === 0) {
        window.removeEventListener("hashchange", changed, true);
        window.removeEventListener("popstate", moved);
        window.removeEventListener("beforeunload", unloading);
        clearTimeout(batchTimer);
        batchTimer = undefined;
        batch = [];
        blocker = null;
        restoring = false;
        restoreCursor = null;
        afterRestore = null;
        allowedURL = null;
      }
    };
  }, []);
}
export function registerNavigationBlocker(value: Blocker) {
  blocker = value;
  return () => {
    if (blocker === value) blocker = null;
  };
}
export function useNavigationGuard() {
  return (action: () => void) => {
    if (blocker) blocker.request(() => perform(action));
    else perform(action);
  };
}
// Only for an intentional write's own URL transition, never ordinary navigation.
// Publish atomically: consecutive committed transitions each get a unique index.
export function commitHash(hash: string) {
  const oldURL = location.href;
  const next = new URL(hash.startsWith("#") ? hash : `#${hash}`, oldURL).href;
  if (next === oldURL) return;
  clearTimeout(batchTimer);
  batchTimer = undefined;
  batch = [];
  allowedURL = null;
  position += 1;
  currentURL = next;
  history.pushState({ ...history.state, [positionKey]: position }, "", next);
  publish(oldURL, next);
}
