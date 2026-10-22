import { useEffect, useRef, useState } from "react";
import { ChevronRight, Workflow } from "lucide-react";
import {
  ApiError,
  message,
  request,
  type AgentStepsResponse,
  type Task,
} from "./api";

const hiddenKeys =
  /^(thought|thoughts|reasoning|reasoning_content|scratchpad|chain_of_thought)$/i;
// Display only bounded public actions. React renders these values as text, never HTML.
export function publicText(value: unknown, limit = 6000): string {
  const text =
    typeof value === "string"
      ? value
      : (JSON.stringify(
          value,
          (key, v) => (hiddenKeys.test(key) ? undefined : v),
          2,
        ) ?? "");
  return text.length > limit
    ? `${text.slice(0, limit)}\n…（界面已截取；不是完整原文）`
    : text;
}
export function controllerLabel(
  execution?: string | null,
  controller?: string | null,
): string {
  if (execution === "legacy_single_call" || controller?.startsWith("legacy_"))
    return "旧版单次调用 · 不是 Agent 工具循环";
  if (execution === "single_agent" && controller === "scripted_test")
    return "脚本测试策略 · 无真实模型推理";
  if (execution === "single_agent" && controller === "live_llm")
    return "真实模型控制器 · 根据已提交元数据";
  return "执行方式未知 · 接口未提供完整元数据";
}
export default function AgentActions({
  task,
  polling,
  refreshKey,
  sessionEpoch,
  onUnauthorized,
}: {
  task: Task;
  polling: boolean;
  refreshKey: number;
  sessionEpoch: number;
  onUnauthorized: (epoch: number) => void;
}) {
  const [data, setData] = useState<AgentStepsResponse | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [retry, setRetry] = useState(0);
  const onUnauthorizedRef = useRef(onUnauthorized);
  onUnauthorizedRef.current = onUnauthorized;
  useEffect(() => {
    setData(null);
    setError("");
    setLoading(false);
  }, [task.id, sessionEpoch]);
  useEffect(() => {
    if (!polling) {
      setLoading(false);
      return;
    }
    let stopped = false;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    request<AgentStepsResponse>(
      `/tasks/${encodeURIComponent(task.id)}/agent-steps`,
      { signal: controller.signal },
    )
      .then((response) => {
        if (stopped) return;
        if (
          !["committed", "not_committed", "legacy"].includes(
            response.availability,
          ) ||
          !Array.isArray(response.items)
        )
          throw new Error("Agent 动作接口格式不符合契约，未展示动作。");
        if (
          response.availability === "committed" &&
          (!task.result_available || task.status !== "succeeded")
        )
          throw new Error("任务尚未确认成功提交，不能展示 Agent 动作。");
        if (
          response.availability === "committed" &&
          response.items.some(
            (step) =>
              step.task_id !== task.id ||
              !["tool_call", "tool_result", "final"].includes(step.kind),
          )
        )
          throw new Error("Agent 动作标识或类型不符合当前任务，未展示动作。");
        setData(response);
      })
      .catch((e) => {
        if (stopped) return;
        setData(null);
        if (e instanceof ApiError && e.status === 401) {
          onUnauthorizedRef.current(sessionEpoch);
          return;
        }
        setError(
          e instanceof ApiError && e.status === 404
            ? "动作接口或任务不存在（404）；可能是旧版后端，未获得动作数据。"
            : e instanceof ApiError && e.status === 503
              ? "Agent 动作文档暂不可读取（503）。这不是“没有动作”，请稍后重试。"
              : message(e),
        );
      })
      .finally(() => {
        if (!stopped) setLoading(false);
      });
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [
    task.id,
    task.status,
    task.result_available,
    polling,
    refreshKey,
    sessionEpoch,
    retry,
  ]);
  return (
    <section
      className="agent-actions"
      aria-label="Agent 工具动作"
      data-testid="agent-actions"
    >
      <div className="agent-actions-heading">
        <Workflow size={17} />
        <h3>Agent 工具动作</h3>
        <span>成功提交后可见</span>
      </div>
      <p className="agent-boundary">
        与上方 MySQL
        后台生命周期不同：这里读取已提交结果中的公开工具动作，不是实时追踪，也不覆盖失败尝试或崩溃前的全部调用。
      </p>
      {loading && !data ? (
        <p className="agent-empty" role="status">
          正在读取已提交的 Agent 动作…
        </p>
      ) : null}
      {!polling && !data && !error ? (
        <p className="agent-empty">自动刷新已暂停；恢复后读取动作。</p>
      ) : null}
      {error ? (
        <div className="notice" role="alert">
          {error}
          <button
            type="button"
            className="text-button"
            disabled={!polling}
            onClick={() => setRetry((v) => v + 1)}
          >
            重新读取 Agent 动作
          </button>
        </div>
      ) : null}
      {data?.availability === "not_committed" ? (
        <p className="agent-empty" data-testid="agent-not-committed">
          尚无成功提交的 Agent
          动作。运行中或失败不代表没有调用工具；本版本不提供这些尝试的完整动作审计。
        </p>
      ) : null}
      {data?.availability === "legacy" ? (
        <p className="agent-empty" data-testid="agent-legacy">
          这是旧版结果，没有 Agent 工具动作。旧单次调用摘要不会被包装成 Agent
          执行轨迹。
        </p>
      ) : null}
      {data?.availability === "committed" ? (
        <>
          <div className="agent-mode" data-testid="agent-controller-mode">
            {controllerLabel(data.execution_kind, data.controller_mode)}
          </div>
          {data.items.length === 0 ? (
            <p className="agent-empty">
              接口返回已提交但无可展示动作；无法据此推断执行了哪些工具。
            </p>
          ) : (
            <ol className="agent-step-list">
              {data.items.slice(0, 16).map((step) => (
                <li key={step.id} data-testid="agent-step">
                  <div className="agent-step-heading">
                    <span>{step.sequence}</span>
                    <strong>
                      {step.kind === "tool_call"
                        ? "调用工具"
                        : step.kind === "tool_result"
                          ? "工具结果"
                          : step.kind === "final"
                            ? "最终答复"
                            : "未知动作"}
                    </strong>
                    {step.tool_name && (
                      <code>{publicText(step.tool_name, 80)}</code>
                    )}
                  </div>
                  {step.kind === "tool_call" && step.arguments !== undefined ? (
                    <>
                      <span className="agent-field-label">参数</span>
                      <pre tabIndex={0} aria-label="工具参数">
                        {publicText(step.arguments, 2200)}
                      </pre>
                    </>
                  ) : null}
                  {step.kind === "tool_result" && step.result !== undefined ? (
                    <pre tabIndex={0} aria-label="工具结果">
                      {publicText(step.result, 4500)}
                    </pre>
                  ) : null}
                  {step.kind === "final" ? (
                    <pre tabIndex={0} aria-label="最终答复摘要">
                      {publicText(step.content, 8500)}
                    </pre>
                  ) : null}
                  {step.truncated ? (
                    <p className="agent-truncated">
                      工具返回已按预算截取；请勿当作完整材料。
                    </p>
                  ) : null}
                  <details>
                    <summary>
                      动作标识 <ChevronRight size={11} />
                    </summary>
                    <code>
                      step_id: {step.id}
                      <br />
                      attempt_id: {step.attempt_id}
                      <br />
                      task_id: {step.task_id}
                      <br />
                      时间: {step.created_at}
                    </code>
                  </details>
                </li>
              ))}
            </ol>
          )}
        </>
      ) : null}
    </section>
  );
}
