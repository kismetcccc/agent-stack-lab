export type Session = {
  user: { id: string; username: string };
  csrf_token: string;
};
export type Task = {
  id: string;
  prompt: string;
  status: string;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  error: string | null;
  result_available: boolean;
  model_mode: string;
  trace_id: string;
  progress: number;
};
export type Step = {
  id: string;
  task_id: string;
  sequence: number;
  kind: string;
  content: unknown;
  created_at: string;
  component?: string;
  trace_id?: string;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(
    path.startsWith("/api/") || path === "/readyz" ? path : `/api/v1${path}`,
    {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    },
  );
  const body =
    response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      response.status,
      body?.error?.message ||
        (response.status === 401
          ? "会话已失效，请重新登录。"
          : response.status === 403
            ? "没有权限访问此资源。"
            : response.status === 404
              ? "任务不存在或不属于当前帐号。"
              : `请求失败 (${response.status})，请稍后重试。`),
      body?.error?.code,
    );
  return body as T;
}
export const message = (e: unknown) =>
  e instanceof Error ? e.message : "网络请求失败，请检查服务连接。";

export type AgentStep = {
  id: string;
  task_id: string;
  sequence: number;
  kind: "tool_call" | "tool_result" | "final";
  content: unknown;
  created_at: string;
  attempt_id: string;
  execution_kind: string;
  controller_mode: string;
  tool_name?: string;
  arguments?: unknown;
  result?: unknown;
  truncated?: boolean;
};
export type AgentStepsResponse = {
  items: AgentStep[];
  availability: "committed" | "not_committed" | "legacy";
  execution_kind: string | null;
  controller_mode: string | null;
};
export type TaskResult = {
  task_id: string;
  content: unknown;
  model_mode: string;
  cache_status: string;
  execution_kind?: string;
  controller_mode?: string;
};
