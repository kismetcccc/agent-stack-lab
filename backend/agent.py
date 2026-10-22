"""Bounded single-controller execution; SQL still owns success and fencing."""

import asyncio
import re
import time
from datetime import UTC, datetime

from backend.agent_errors import AgentBudgetError, AgentProtocolError
from backend.agent_tools import execute_tool, json_bytes
from backend.agent_types import Final, ToolCall


class ScriptedController:
    """Explicit test policy: markers select branches, never claims semantic reasoning."""

    controller_mode = "scripted_test"

    async def next(self, prompt, observations, deadline):
        if not observations:
            return ToolCall("read-1", "read_text", {"offset": 0, "length": 1000})
        marker = re.search(r"\[search:([^\]\n]{1,200})\]", prompt)
        if marker and len(observations) == 1:
            return ToolCall(
                "search-1",
                "search_text",
                {
                    "query": marker[1],
                    "limit": 5,
                    "offset": prompt.index("材料：") + len("材料：") if "材料：" in prompt else marker.end(),
                },
            )
        # Search miss branches directly to final; stats marker requires explicit material boundary.
        searched = next((o for o in observations if o["tool_name"] == "search_text"), None)
        wants_stats = "[stats]" in prompt and "材料：" in prompt
        if wants_stats and not any(o["tool_name"] == "numeric_stats" for o in observations):
            if searched is None or searched["result"].get("matches"):
                start = prompt.index("材料：") + len("材料：")
                if start < len(prompt):
                    return ToolCall("stats-1", "numeric_stats", {"start": start, "end": len(prompt)})
        stats = next((o["result"] for o in observations if o["tool_name"] == "numeric_stats"), None)
        excerpt = observations[0]["result"].get("text", "")
        suffix = "\n数值统计：" + json_bytes(stats).decode() if stats else ""
        return Final("[deterministic 脚本测试控制器；无真实模型推理]\n" + excerpt + suffix)


def safe_bytes(value, *, text=False):
    try:
        return value.encode("utf-8") if text else json_bytes(value)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise AgentProtocolError("invalid decision encoding") from exc


async def run_agent(task, controller, *, max_decisions=6, max_tools=5, seconds=60):
    # Trusted knobs may only tighten limits. Wall-clock lease is converted once to monotonic deadline.
    remaining = min(seconds, 60, task.lease_until - time.time() - 15)
    if remaining <= 0:
        raise AgentBudgetError("insufficient lease margin")
    deadline = time.monotonic() + remaining
    decisions = min(max_decisions, 6)
    tool_limit = min(max_tools, 5)
    observations, steps, call_ids = [], [], set()
    total_bytes = 0

    def check():
        if time.monotonic() >= deadline:
            raise AgentBudgetError("execution deadline exceeded")

    def record(kind, content, **extra):
        sequence = len(steps) + 1
        steps.append(
            {
                "id": f"{task.attempt_id}:{sequence}",
                "task_id": task.id,
                "attempt_id": task.attempt_id,
                "sequence": sequence,
                "kind": kind,
                "content": content,
                "created_at": datetime.now(UTC).isoformat(),
                "execution_kind": "single_agent",
                "controller_mode": controller.controller_mode,
                **extra,
            }
        )

    try:
        async with asyncio.timeout(remaining):
            for _ in range(decisions):
                check()
                decision = await controller.next(task.prompt, observations, deadline)
                check()
                if type(decision) is Final:
                    if not isinstance(decision.content, str) or not decision.content.strip():
                        raise AgentProtocolError("empty final")
                    if len(safe_bytes(decision.content, text=True)) > 8192:
                        raise AgentBudgetError("final too large")
                    record("final", decision.content)
                    return {
                        "task_id": task.id,
                        "attempt_id": task.attempt_id,
                        "content": decision.content,
                        "model_mode": task.model_mode,
                        "execution_kind": "single_agent",
                        "controller_mode": controller.controller_mode,
                        "steps": steps,
                    }
                if type(decision) is not ToolCall:
                    raise AgentProtocolError("unknown decision")
                if (
                    not isinstance(decision.call_id, str)
                    or not decision.call_id.strip()
                    or len(safe_bytes(decision.call_id, text=True)) > 128
                    or decision.call_id in call_ids
                ):
                    raise AgentProtocolError("invalid or repeated call id")
                if len(observations) >= tool_limit:
                    raise AgentBudgetError("tool budget exceeded")
                if len(safe_bytes(decision.arguments)) > 2048:
                    raise AgentBudgetError("arguments too large")
                check()
                result = execute_tool(decision.tool_name, decision.arguments, task.prompt)
                check()
                size = len(safe_bytes(result))
                total_bytes += size
                if size > 4096 or total_bytes > 16384:
                    raise AgentBudgetError("tool output budget exceeded")
                call_ids.add(decision.call_id)
                common = {"tool_name": decision.tool_name, "arguments": decision.arguments}
                record("tool_call", "调用只读工具 " + decision.tool_name, **common)
                record(
                    "tool_result",
                    "只读工具返回 " + decision.tool_name,
                    **common,
                    result=result,
                    truncated=bool(result.get("truncated", False)),
                )
                observations.append({"call_id": decision.call_id, **common, "result": result})
    except TimeoutError as exc:
        raise AgentBudgetError("execution deadline exceeded") from exc
    raise AgentBudgetError("decision budget exhausted without final")
