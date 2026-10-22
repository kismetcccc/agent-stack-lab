#!/usr/bin/env python3
"""Bounded, deterministic-only HTTP example against real Compose adapters.

Uses only Python's standard library. Importing this module never makes a request.
Run: TEST_BASE_URL=http://127.0.0.1:8080 python scripts/test-http-smoke.py
The synthetic account/task remain in the development database; success logs sessions out.
A failed or interrupted run may leave a synthetic session until expiry; it is not retried.
"""

import http.cookiejar
import json
import os
import queue
import secrets
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
TOTAL_SECONDS = 180
REQUEST_SECONDS = 10
MAX_RESPONSE_BYTES = 256 * 1024
PROMPT = "目标：[search:销量] [stats]\n材料：销量 10 20 30"
SUCCESS = (
    "PASS: deterministic HTTP register/logout/login/CSRF → idempotent task → "
    "committed result, lifecycle events, attempts and Agent actions → logout/401"
)


class SmokeFailure(Exception):
    """Only fixed local labels and numeric statuses may enter public diagnostics."""


def require(condition, label):
    if not condition:
        raise SmokeFailure(label)


def validate_base_url(value):
    # Accept an explicit origin, not credentials, a path prefix or hidden URL data.
    try:
        require(isinstance(value, str) and bool(value), "unsafe_base_url")
        require(not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value), "unsafe_base_url")
        require(not any(c in value for c in ("@", "?", "#", "\\")), "unsafe_base_url")
        parsed = urllib.parse.urlsplit(value)
        require(parsed.scheme in {"http", "https"} and bool(parsed.hostname), "unsafe_base_url")
        require(parsed.username is None and parsed.password is None, "unsafe_base_url")
        require(parsed.path in {"", "/"} and "%" not in parsed.netloc, "unsafe_base_url")
        require(parsed.port is None or 1 <= parsed.port <= 65535, "unsafe_base_url")
        return value.rstrip("/")
    except (ValueError, UnicodeError):
        raise SmokeFailure("unsafe_base_url") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise SmokeFailure("redirect_refused")


def build_opener():
    # No inherited proxy credentials; HTTPS keeps certificate and hostname checks.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )


class HttpClient:
    def __init__(
        self, base_url, *, opener=None, total_seconds=TOTAL_SECONDS,
        request_seconds=REQUEST_SECONDS, max_response_bytes=MAX_RESPONSE_BYTES,
        clock=time.monotonic, sleep=time.sleep,
    ):
        self.base_url = validate_base_url(base_url)
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + total_seconds
        self.request_seconds = request_seconds
        self.max_response_bytes = max_response_bytes
        self.opener = opener if opener is not None else build_opener()

    def remaining(self):
        remaining = self.deadline - self.clock()
        require(remaining > 0, "deadline_exceeded")
        return remaining

    def pause(self):
        self.sleep(min(1, self.remaining()))

    def _roundtrip(self, request, expected_status, timeout):
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.getcode()
            if status != expected_status:
                # Never include a response body, reason, URL, headers or provider error.
                raise SmokeFailure(f"http_status_{int(status)}")
            body = response.read(self.max_response_bytes + 1)
        require(len(body) <= self.max_response_bytes, "response_too_large")
        if status == 204:
            require(not body, "unexpected_response_body")
            return None
        if status >= 400:
            return None  # The logout check needs the status, not arbitrary error text.
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise SmokeFailure("malformed_response") from None
        require(isinstance(payload, dict), "malformed_response")
        return payload

    def request(self, method, path, *, data=None, headers=None, status=200):
        timeout = min(self.request_seconds, self.remaining())
        request_deadline = self.clock() + timeout
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        result = queue.Queue(maxsize=1)

        def exchange():
            try:
                remaining = min(self.remaining(), request_deadline - self.clock())
                require(remaining > 0, "request_timeout")
                result.put((True, self._roundtrip(request, status, remaining)))
            except SmokeFailure as error:
                result.put((False, error))
            except Exception:
                result.put((False, SmokeFailure("transport_error")))

        # Socket timeouts alone are inactivity limits, not wall-clock limits (DNS,
        # headers and a trickling body can stall). Bound the entire exchange too.
        # No retry or later workflow request is issued after timeout; in-flight
        # server work may still finish. A daemon cannot keep the helper alive.
        threading.Thread(target=exchange, daemon=True).start()
        try:
            wait_seconds = min(self.remaining(), request_deadline - self.clock())
            require(wait_seconds > 0, "request_timeout")
            ok, value = result.get(timeout=wait_seconds)
        except queue.Empty:
            self.remaining()
            raise SmokeFailure("request_timeout") from None
        self.remaining()
        require(self.clock() < request_deadline, "request_timeout")
        if not ok:
            raise value
        return value


def require_ready(payload):
    require(payload.get("status") == "ready", "not_ready")
    require(payload.get("mode") == "production", "real_adapters_required")
    require(payload.get("model_mode") == "deterministic", "deterministic_required")
    dependencies = payload.get("dependencies")
    require(isinstance(dependencies, dict), "real_adapters_required")
    require(all(dependencies.get(name) == "up" for name in ("mysql", "mongo", "kafka")),
            "real_adapters_required")
    require("sqlite" not in dependencies, "real_adapters_required")


def auth_data(payload, username, owner=None):
    user, csrf = payload.get("user"), payload.get("csrf_token")
    require(isinstance(user, dict) and user.get("username") == username, "auth_identity_mismatch")
    require(isinstance(user.get("id"), str) and bool(user["id"]), "auth_identity_mismatch")
    require(owner is None or user["id"] == owner, "auth_identity_mismatch")
    require(isinstance(csrf, str) and bool(csrf), "missing_csrf")
    return user["id"], csrf


def require_task(payload, task_id=None):
    value = payload.get("id")
    try:
        require(isinstance(value, str) and str(uuid.UUID(value)) == value, "invalid_task_id")
    except (ValueError, AttributeError):
        raise SmokeFailure("invalid_task_id") from None
    require(task_id is None or task_id == value, "idempotency_or_task_mismatch")
    require(payload.get("prompt") == PROMPT, "task_prompt_mismatch")
    require(payload.get("model_mode") == "deterministic", "deterministic_required")
    require(payload.get("status") != "failed", "task_failed")
    require(payload.get("status") in {"pending", "ready", "running", "retry_wait", "succeeded"},
            "invalid_task_status")
    return value


def items(payload, label):
    value = payload.get("items")
    require(isinstance(value, list) and all(isinstance(item, dict) for item in value), label)
    return value


def verify_committed(client, task_id, detail):
    path = f"/api/v1/tasks/{task_id}"
    require(detail.get("result_available") is True, "result_not_committed")
    result = client.request("GET", path + "/results")
    require(result.get("task_id") == task_id, "result_task_mismatch")
    require(isinstance(result.get("content"), str) and bool(result["content"].strip()), "empty_result")
    require(result.get("model_mode") == "deterministic", "deterministic_required")
    require(result.get("execution_kind") == "single_agent" and result.get("controller_mode") == "scripted_test",
            "agent_mode_mismatch")
    require(result.get("cache_status") in {"hit", "miss", "unavailable", "disabled"}, "invalid_cache_status")

    # Relay acknowledgement can be recorded after the consumer/executor finish.
    # Require all real lifecycle components eventually, never a global ordering.
    expected = {("pending", "api"), ("outbox_sent", "relay"), ("ready", "consumer"),
                ("running", "executor"), ("succeeded", "executor")}
    while True:
        events = items(client.request("GET", path + "/events"), "invalid_events")
        require(all(event.get("task_id") == task_id and event.get("trace_id") == detail.get("trace_id")
                    for event in events), "event_task_mismatch")
        if expected <= {(event.get("kind"), event.get("component")) for event in events}:
            break
        client.pause()

    attempts = items(client.request("GET", path + "/attempts"), "invalid_attempts")
    succeeded = {attempt.get("id") for attempt in attempts
                 if attempt.get("outcome") == "succeeded" and attempt.get("finished_at")}
    require(bool(succeeded), "no_successful_attempt")
    require(detail.get("attempt_count") == len(attempts), "attempt_count_mismatch")
    actions = client.request("GET", path + "/agent-steps")
    require(actions.get("availability") == "committed", "actions_not_committed")
    require(actions.get("execution_kind") == "single_agent"
            and actions.get("controller_mode") == "scripted_test", "agent_mode_mismatch")
    steps = items(actions, "invalid_agent_actions")
    require(len(steps) == 7, "invalid_agent_actions")
    attempt_id = steps[0].get("attempt_id")
    require(attempt_id in succeeded, "action_attempt_mismatch")
    for sequence, step in enumerate(steps, 1):
        require(step.get("task_id") == task_id and step.get("attempt_id") == attempt_id
                and step.get("sequence") == sequence and step.get("id") == f"{attempt_id}:{sequence}",
                "invalid_agent_actions")
        require(step.get("execution_kind") == "single_agent" and step.get("controller_mode") == "scripted_test",
                "agent_mode_mismatch")
    for index, tool in enumerate(("read_text", "search_text", "numeric_stats")):
        call, observation = steps[index * 2:index * 2 + 2]
        require(call.get("kind") == "tool_call" and observation.get("kind") == "tool_result"
                and call.get("tool_name") == tool and observation.get("tool_name") == tool
                and isinstance(call.get("arguments"), dict) and observation.get("arguments") == call["arguments"]
                and isinstance(observation.get("result"), dict) and isinstance(observation.get("truncated"), bool),
                "invalid_agent_actions")
    require(steps[-1].get("kind") == "final" and steps[-1].get("content") == result["content"],
            "final_result_mismatch")


def run_smoke(client):
    require(client.request("GET", "/healthz").get("status") == "ok", "unhealthy")
    # This gate MUST precede even registration, not merely task submission.
    require_ready(client.request("GET", "/readyz"))
    credentials = {"username": "smoke_" + uuid.uuid4().hex[:16], "password": secrets.token_urlsafe(24)}
    registered = client.request("POST", "/api/v1/auth/register", data=credentials, status=201)
    owner, csrf = auth_data(registered, credentials["username"])
    client.request("POST", "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}, status=204)
    logged_in = client.request("POST", "/api/v1/auth/login", data=credentials)
    _, csrf = auth_data(logged_in, credentials["username"], owner)
    refreshed = client.request("GET", "/api/v1/auth/me")
    _, latest_csrf = auth_data(refreshed, credentials["username"], owner)
    require(latest_csrf != csrf, "csrf_not_rotated")
    headers = {"X-CSRF-Token": latest_csrf, "Idempotency-Key": str(uuid.uuid4())}
    task = client.request("POST", "/api/v1/tasks", data={"prompt": PROMPT}, headers=headers, status=202)
    task_id = require_task(task)
    replay = client.request("POST", "/api/v1/tasks", data={"prompt": PROMPT}, headers=headers, status=202)
    require_task(replay, task_id)
    while True:
        detail = client.request("GET", f"/api/v1/tasks/{task_id}")
        require_task(detail, task_id)
        if detail["status"] == "succeeded":
            break
        client.pause()
    verify_committed(client, task_id, detail)
    client.request("POST", "/api/v1/auth/logout", headers={"X-CSRF-Token": latest_csrf}, status=204)
    client.request("GET", f"/api/v1/tasks/{task_id}", status=401)


def main():
    try:
        run_smoke(HttpClient(os.getenv("TEST_BASE_URL", DEFAULT_BASE_URL)))
    except SmokeFailure as error:
        print(f"FAIL: HTTP smoke: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("FAIL: HTTP smoke: interrupted", file=sys.stderr)
        return 130
    except Exception:
        print("FAIL: HTTP smoke: unexpected_error", file=sys.stderr)
        return 1
    print(SUCCESS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
