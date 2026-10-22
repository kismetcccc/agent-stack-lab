"""Capture synthetic baseline evidence, NOT a semantic-quality test or provider run.

Only task-domain response fields are exported; never dump clients, auth responses,
headers, environment, arbitrary exceptions, or connection details.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import httpx
from pymongo import MongoClient
from redis import Redis
from sqlalchemy import create_engine, text

from backend.agent import run_agent
from backend.agent_errors import AGENT_ERROR_CODES
from backend.agent_tools import json_bytes
from backend.agent_types import ToolCall

SAFE_CODES = AGENT_ERROR_CODES | {"permanent_failure", "transient_failure", "lease_expired"}
# Exact public strings verified in backend/app.py, auth.py and service.py.
# Unknown text is omitted, never reconstructed from a code or raw exception.
PUBLIC_MESSAGES = {
    **{code: {"执行失败；错误信息已脱敏"} for code in SAFE_CODES},
    "validation_error": {"输入格式或长度不符合要求"},
    "body_too_large": {"请求过大"},
    "origin_forbidden": {"请求来源不被允许"},
    "not_found": {"请求路径不存在", "任务不存在"},
    "http_error": {"请求方法不被允许"},
    "database_unavailable": {"数据库暂不可用"},
    "internal_error": {"请求处理失败"},
    "username_exists": {"用户名已存在"},
    "invalid_credentials": {"用户名或密码错误"},
    "unauthorized": {"请先登录"},
    "csrf_failed": {"CSRF 校验失败"},
    "idempotency_conflict": {"同一幂等键不能用于不同请求"},
    "result_not_ready": {"任务尚未成功"},
    "document_unavailable": {"结果存储暂不可用", "结果文档暂不可读", "结果文档元数据无效"},
}
STEP_KEYS = "id task_id attempt_id sequence kind content created_at execution_kind controller_mode tool_name arguments result truncated component trace_id".split()
RESULT_KEYS = "task_id content model_mode cache_status execution_kind controller_mode".split()


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def safe_error(value):
    if value is None:
        return None
    value = value if isinstance(value, dict) else {}
    code, message = value.get("code"), value.get("message")
    known_code = isinstance(code, str) and code in PUBLIC_MESSAGES
    known_message = known_code and isinstance(message, str) and message in PUBLIC_MESSAGES[code]
    return {
        "code": code if known_code else None,
        "message": message if known_message else None,
        "code_exported": known_code,
        "message_exported": known_message,
    }


def response_error(response):
    try:
        body = response.json()
    except ValueError:
        body = {}
    return safe_error(body.get("error", {}) if isinstance(body, dict) else {})


def facts(actions, result):
    return {
        "tool_results_json_utf8": [
            len(json_bytes(s["result"])) for s in actions.get("items", []) if "result" in s
        ],
        "final_utf8": len(result.get("content", "").encode("utf-8")),
    }


def authenticated(stack, base, *, transport=None):
    client = stack.enter_context(httpx.Client(base_url=base, timeout=15, transport=transport))
    credentials = {"username": "judge_" + uuid.uuid4().hex[:20], "password": "Ephemeral!" + uuid.uuid4().hex}
    response = client.post("/api/v1/auth/register", json=credentials)
    if response.status_code != 201:
        raise RuntimeError("auth_registration_unavailable")
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    if client.post("/api/v1/auth/logout").status_code != 204:
        raise RuntimeError("auth_logout_unavailable")
    response = client.post("/api/v1/auth/login", json=credentials)
    if response.status_code != 200:
        raise RuntimeError("auth_login_unavailable")
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    response = client.get("/api/v1/auth/me")
    if response.status_code != 200:
        raise RuntimeError("auth_me_unavailable")
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def require_stores(client, stack):
    health = client.get("/readyz")
    if health.status_code != 200:
        raise RuntimeError("readiness_unavailable")
    data = health.json()
    if data["mode"] != "production" or data["model_mode"] != "deterministic":
        raise RuntimeError("wrong_capture_mode")
    if any(data["dependencies"].get(name) != "up" for name in ("mysql", "kafka", "mongo")):
        raise RuntimeError("real_stores_unavailable")
    if not os.environ.get("DATABASE_URL", "").startswith("mysql"):
        raise RuntimeError("real_mysql_required")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    stack.callback(engine.dispose)
    with engine.connect() as conn:
        conn.execute(text("SELECT VERSION()")).scalar_one()
    mongo = stack.enter_context(MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000))
    mongo.admin.command("ping")
    redis = stack.enter_context(Redis.from_url(os.environ["REDIS_URL"], socket_timeout=3))
    if not redis.ping():
        raise RuntimeError("real_redis_unavailable")
    return {"mysql": "up", "kafka": "up", "mongo": "up", "redis": "up"}


def task_total(client):
    response = client.get("/api/v1/tasks?limit=1")
    if response.status_code != 200:
        raise RuntimeError("task_listing_unavailable")
    return response.json()["total"]


def capture_api(case, row, client, other, anonymous, ownership_ids):
    rejection_probe = case["type"] == "input_rejection"
    if rejection_probe:
        row["rejection_task_count"] = {"before": task_total(client)}
    response = client.post(
        "/api/v1/tasks", json={"prompt": case["prompt"]}, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    row["submit_http_status"] = response.status_code
    if rejection_probe:
        count = row["rejection_task_count"]
        count["after"] = task_total(client)
        count["unchanged"] = count["before"] == count["after"]
    if response.status_code != 202:
        row["status"] = "input_rejected"
        # Export only exact known public error pairs, never validation input/context.
        row["safe_error"] = response_error(response)
        row["capture_complete"] = response.status_code in (400, 409, 413, 422)
        return
    task_id = response.json()["id"]
    path = f"/api/v1/tasks/{task_id}"
    deadline = time.monotonic() + 120
    while True:
        response = client.get(path)
        if response.status_code != 200:
            raise RuntimeError("task_read_unavailable")
        task = response.json()
        if task["status"] in ("succeeded", "failed"):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("task_completion_timeout")
        time.sleep(0.5)
    row.update(
        task_id=task_id,
        status=task["status"],
        model_mode=task["model_mode"],
        normalized_prompt=task["prompt"],
        safe_error=safe_error(task.get("error")),
    )
    for endpoint in ("attempts", "events", "agent-steps", "results"):
        response = client.get(f"{path}/{endpoint}")
        row.setdefault("read_http_status", {})[endpoint] = response.status_code
        if endpoint == "results" and response.status_code == 409:
            row["results"] = None
            continue
        if response.status_code != 200:
            raise RuntimeError("evidence_read_unavailable")
        data = response.json()
        if endpoint == "results":
            row["results"] = pick(data, RESULT_KEYS)
        elif endpoint == "agent-steps":
            row["actions"] = pick(data, ["availability", "execution_kind", "controller_mode"])
            row["actions"]["items"] = [pick(step, STEP_KEYS) for step in data["items"]]
        else:
            keys = (
                STEP_KEYS if endpoint == "events" else ["id", "fence", "started_at", "finished_at", "outcome"]
            )
            row[endpoint] = [pick(item, keys) for item in data["items"]]
    if row["results"] is not None:
        response = client.get(f"{path}/results")
        row["repeat_result_http_status"] = response.status_code
        if response.status_code != 200:
            raise RuntimeError("repeat_result_unavailable")
        row["results_repeat"] = pick(response.json(), RESULT_KEYS)
        stable_keys = [key for key in RESULT_KEYS if key != "cache_status"]
        row["result_stable_excluding_cache_status"] = pick(row["results"], stable_keys) == pick(
            row["results_repeat"], stable_keys
        )
    row["byte_facts"] = facts(row["actions"], row["results"] or {})
    if case["id"] in ownership_ids:
        row["owner_checks"] = [
            {
                "path": endpoint or "task",
                "nonowner_status": other.get(path + endpoint).status_code,
                "unauthenticated_status": anonymous.get(path + endpoint).status_code,
            }
            for endpoint in ("", "/results", "/agent-steps")
        ]
    row["capture_complete"] = True


def capture_runtime(case, row):
    fixture = case["fixture"]

    class SequenceController:
        controller_mode = "scripted_test"

        def __init__(self):
            self.decisions = iter(fixture["decisions"])
            self.observations = []
            self.requests = []

        async def next(self, prompt, observations, deadline):
            self.observations = list(observations)
            decision = next(self.decisions)
            self.requests.append(decision)
            return ToolCall(decision["call_id"], decision["tool_name"], decision["arguments"])

    controller = SequenceController()
    task = SimpleNamespace(
        id=case["id"],
        attempt_id="isolated-fixture",
        prompt=case["prompt"],
        model_mode="deterministic",
        lease_until=time.time() + fixture["task"]["lease_seconds_from_now"],
    )
    try:
        doc = asyncio.run(run_agent(task, controller, **fixture["run_agent_kwargs"]))
        row.update(status="succeeded", results=pick(doc, RESULT_KEYS), actions={"items": doc["steps"]})
    except Exception as exc:
        if getattr(exc, "code", None) not in SAFE_CODES:
            raise
        row.update(
            status="rejected",
            safe_error={"code": exc.code},
            results=None,
            actions={"items": [], "availability": "not_returned_on_error"},
        )
    row.update(
        fixture_requested_decisions=controller.requests,
        fixture_observations=controller.observations,
        completed_tool_calls_observed=len(controller.observations),
        capture_complete=True,
    )
    row["byte_facts"] = facts({"items": controller.observations}, row["results"] or {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="/reports/judge-evidence.json")
    parser.add_argument(
        "--runtime-only", action="store_true", help="isolated fixtures only; never API evidence"
    )
    args = parser.parse_args()
    source = Path(__file__).with_name("cases.json").read_bytes()
    suite = json.loads(source)
    commit = os.getenv("JUDGE_COMMIT", "unknown")
    if commit != "unknown" and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid commit identifier")
    evidence = {
        "schema_version": 1,
        "commit": commit,
        "cases_sha256": hashlib.sha256(source).hexdigest(),
        "quality_verdict": "not_assessed_capture_only",
        "provider_status": "not_run",
        "cases": [],
        "capture_complete": False,
        "scope": "runtime_unit_only" if args.runtime_only else "real_api_and_runtime_unit",
    }
    failed = False
    try:
        with ExitStack() as stack:
            if not args.runtime_only:
                base = os.getenv("TEST_BASE_URL", "http://localhost:8080")
                client = authenticated(stack, base)
                evidence["stores"] = require_stores(client, stack)
                other = authenticated(stack, base)
                anonymous = stack.enter_context(httpx.Client(base_url=base, timeout=15))
            for case in suite["cases"]:
                runtime = case["type"] == "runtime_probe"
                if args.runtime_only and not runtime:
                    continue
                row = {
                    "case_id": case["id"],
                    "goal": case["goal"],
                    "prompt": case["prompt"],
                    "mode": "runtime_unit" if runtime else "real_api",
                    "capture_complete": False,
                    "attempts": [],
                    "events": [],
                    "actions": {},
                    "results": None,
                    "owner_checks": [],
                }
                evidence["cases"].append(row)
                try:
                    if runtime:
                        capture_runtime(case, row)
                    else:
                        capture_api(
                            case, row, client, other, anonymous, suite["ownership_probes"]["case_ids"]
                        )
                    failed |= not row["capture_complete"]
                except Exception:
                    row["capture_error"] = "capture_incomplete_or_infrastructure_unavailable"
                    failed = True
            evidence["capture_complete"] = not failed
    except Exception:
        evidence["capture_error"] = "setup_incomplete_or_infrastructure_unavailable"
        failed = True
    finally:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(
        "Evidence capture complete; semantic quality NOT assessed."
        if not failed
        else "Evidence capture INCOMPLETE; see sanitized evidence."
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
