"""Collector-only regression checks. Mock HTTP is never real API evidence."""

from contextlib import ExitStack

import httpx
from capture import authenticated, capture_api, pick, safe_error


def test_auth_refresh_uses_latest_csrf_in_memory():
    seen = []

    def respond(request):
        path = request.url.path
        seen.append(path)
        if path.endswith("register"):
            return httpx.Response(201, json={"csrf_token": "register-fixture"})
        if path.endswith("logout"):
            assert request.headers["X-CSRF-Token"] == "register-fixture"
            return httpx.Response(204)
        if path.endswith("login"):
            return httpx.Response(200, json={"csrf_token": "login-fixture"})
        if path.endswith("me"):
            return httpx.Response(200, json={"csrf_token": "refreshed-fixture"})
        assert path == "/api/v1/tasks"
        assert request.headers["X-CSRF-Token"] == "refreshed-fixture"
        return httpx.Response(422, json={"detail": "synthetic rejection"})

    with ExitStack() as stack:
        client = authenticated(stack, "http://collector.invalid", transport=httpx.MockTransport(respond))
        assert client.post("/api/v1/tasks", json={"prompt": ""}).status_code == 422
    assert seen == [
        f"/api/v1/{suffix}" for suffix in ("auth/register", "auth/logout", "auth/login", "auth/me", "tasks")
    ]


def test_rejected_input_records_actual_task_counts():
    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"total": 7})
        return httpx.Response(
            422,
            json={
                "error": {"code": "validation_error", "message": "输入格式或长度不符合要求"},
                "input": "secret",
            },
        )

    with httpx.Client(base_url="http://collector.invalid", transport=httpx.MockTransport(respond)) as client:
        row = {}
        capture_api({"id": "J20", "type": "input_rejection", "prompt": ""}, row, client, None, None, [])
    assert row["rejection_task_count"] == {"before": 7, "after": 7, "unchanged": True}
    assert row["capture_complete"] is True
    assert "detail" not in row
    assert row["safe_error"]["code"] == "validation_error"
    assert row["safe_error"]["message"] == "输入格式或长度不符合要求"
    assert "secret" not in str(row)


def test_projected_fields_and_errors_exclude_secrets():
    assert pick({"content": "synthetic", "csrf_token": "secret"}, ["content"]) == {"content": "synthetic"}
    assert safe_error({"code": "secret", "message": "secret"}) == {
        "code": None,
        "message": None,
        "code_exported": False,
        "message_exported": False,
    }
    error = safe_error({"code": "agent_tool_rejected", "message": "执行失败；错误信息已脱敏"})
    assert error["message_exported"] and error["message"] == "执行失败；错误信息已脱敏"
    for code, message in (("validation_error", "secret"), ("secret", "请求过大"), ([], {})):
        projected = safe_error({"code": code, "message": message, "input": "secret"})
        assert projected["message"] is None and not projected["message_exported"]
        assert "secret" not in str(projected)


def test_repeat_result_difference_is_preserved_not_scored():
    reads = 0

    def respond(request):
        nonlocal reads
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(202, json={"id": "synthetic-task"})
        if path.endswith("results"):
            reads += 1
            return httpx.Response(200, json={"content": f"observed-{reads}", "cache_status": "hit"})
        if path.endswith(("attempts", "events", "agent-steps")):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(
            200, json={"status": "succeeded", "model_mode": "deterministic", "prompt": "trimmed"}
        )

    with httpx.Client(base_url="http://collector.invalid", transport=httpx.MockTransport(respond)) as client:
        row = {}
        capture_api({"id": "fixture", "type": "api_task", "prompt": " trimmed "}, row, client, None, None, [])
    assert row["normalized_prompt"] == "trimmed"
    assert row["results"]["content"] == "observed-1"
    assert row["results_repeat"]["content"] == "observed-2"
    assert row["result_stable_excluding_cache_status"] is False
    assert "quality_verdict" not in row


def test_unauthorized_submission_is_incomplete_capture():
    for status in (401, 403, 503):
        with httpx.Client(
            base_url="http://collector.invalid",
            transport=httpx.MockTransport(lambda request: httpx.Response(status)),
        ) as client:
            row = {}
            capture_api(
                {"id": "fixture", "type": "api_task", "prompt": "synthetic"}, row, client, None, None, []
            )
        assert row["submit_http_status"] == status
        assert row["capture_complete"] is False
