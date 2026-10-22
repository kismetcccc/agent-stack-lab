#!/usr/bin/env python3
"""Real HTTP core-cycle smoke; standard library, usable against Compose or Kind."""

import http.cookiejar
import json
import os
import time
import urllib.request
import uuid

base = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
cookies = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def request(path, data=None, headers=None):
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(
        base + path, data=json.dumps(data).encode() if data is not None else None, headers=request_headers
    )
    with client.open(req, timeout=15) as response:
        return json.load(response)


request("/healthz")
request("/readyz")
user = request(
    "/api/v1/auth/register",
    {"username": "smoke_" + uuid.uuid4().hex[:16], "password": "Smoke-only!42-password"},
)
headers = {"X-CSRF-Token": user["csrf_token"], "Idempotency-Key": str(uuid.uuid4())}
task = request("/api/v1/tasks", {"prompt": "Explain the purpose of the transactional outbox"}, headers)
assert (
    request("/api/v1/tasks", {"prompt": "Explain the purpose of the transactional outbox"}, headers)["id"]
    == task["id"]
)
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    detail = request(f"/api/v1/tasks/{task['id']}")
    assert detail["status"] != "failed", detail
    if detail["status"] == "succeeded":
        result = request(f"/api/v1/tasks/{task['id']}/results")
        assert result["content"] and result["model_mode"] == "deterministic"
        assert request(f"/api/v1/tasks/{task['id']}/events")["items"]
        print("PASS: HTTP registration → idempotent task → worker success → durable result and steps")
        break
    time.sleep(1)
else:
    raise AssertionError("HTTP business cycle timed out")
