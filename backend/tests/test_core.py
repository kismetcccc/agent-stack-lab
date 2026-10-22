import json

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import Outbox, Task, now
from backend.domain import TRANSITIONS, PermanentError, transition
from backend.migrate import migrate
from backend.runtime import Runtime


@pytest.fixture
def runtime():
    runtime = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///:memory:"))
    migrate(runtime.engine)
    return runtime


@pytest.fixture
def client(runtime):
    from backend.app import create_app

    return TestClient(create_app(runtime))


def account(client, name="learner"):
    response = client.post("/api/v1/auth/register", json={"username": name, "password": "ephemeral-password"})
    assert response.status_code == 201
    return {"X-CSRF-Token": response.json()["csrf_token"], "Idempotency-Key": "one"}


def enqueue(runtime, owner="owner", key="key"):
    task = runtime.tasks.create(owner, key, "hello", "trace")
    runtime.tasks.relay_once()
    event = runtime.bus.messages[-1][1]
    runtime.tasks.receive(event)
    return task, event


def test_auth_idempotency_and_ownership(client):
    assert client.get("/api/v1/tasks").status_code == 401
    headers = account(client)
    assert client.post("/api/v1/tasks", json={"prompt": "hello"}).status_code == 403
    first = client.post("/api/v1/tasks", json={"prompt": "hello"}, headers=headers)
    assert first.status_code == 202
    assert (
        client.post("/api/v1/tasks", json={"prompt": "hello"}, headers=headers).json()["id"]
        == first.json()["id"]
    )
    assert client.post("/api/v1/tasks", json={"prompt": "different"}, headers=headers).status_code == 409
    assert client.get("/api/v1/tasks?limit=101").status_code == 422
    refreshed = client.get("/api/v1/auth/me").json()
    headers["X-CSRF-Token"] = refreshed["csrf_token"]
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/tasks").status_code == 401
    account(client, "other")
    task_id = first.json()["id"]
    for suffix in ("", "/events", "/results"):
        assert client.get("/api/v1/tasks/" + task_id + suffix).status_code == 404
    assert client.get("/api/v1/tasks").json()["total"] == 0


def test_pipeline_duplicate_inbox_and_result(runtime):
    task, event = enqueue(runtime)
    assert runtime.tasks.receive(event) is False
    assert runtime.tasks.execute_once()
    assert runtime.tasks.get("owner", task["id"])["status"] == "succeeded"
    assert "deterministic" in runtime.tasks.document("owner", task["id"])["content"]
    assert len(runtime.tasks.document("owner", task["id"], True)["items"]) == 3
    assert not runtime.tasks.execute_once()


def test_expiry_fence_and_bounded_retry(runtime):
    task, _ = enqueue(runtime)
    stale = runtime.tasks.claim()
    with runtime.sessions() as session, session.begin():
        stored = session.get(Task, task["id"])
        stored.lease_until = now() - 1
    assert not runtime.tasks.finalize(stale, "orphan")
    runtime.tasks.recover()
    with runtime.sessions() as session, session.begin():
        stored = session.get(Task, task["id"])
        assert stored.status == "retry_wait"
        stored.next_attempt_at = 0
    runtime.tasks.recover()
    current = runtime.tasks.claim()
    assert current.fence > stale.fence
    assert not runtime.tasks.finalize(stale, "orphan")
    assert runtime.tasks.finalize(current, "current-result")


def test_permanent_failure_dlq(runtime):
    task, _ = enqueue(runtime)

    def fail(task):
        raise PermanentError("secret-provider-message")

    runtime.model.run = fail
    runtime.tasks.execute_once()
    view = runtime.tasks.get("owner", task["id"])
    assert view["status"] == "failed"
    assert "secret" not in json.dumps(view)
    runtime.tasks.relay_once()
    assert runtime.bus.messages[-1][0] == runtime.settings.dlq_topic


def test_document_failure_never_success(runtime):
    task, _ = enqueue(runtime)
    runtime.documents.save = lambda *args: (_ for _ in ()).throw(ConnectionError("offline"))
    runtime.tasks.execute_once()
    assert runtime.tasks.get("owner", task["id"])["status"] == "retry_wait"


def test_outbox_publish_failure_retains_pending(runtime):
    task = runtime.tasks.create("owner", "one", "hello", "trace")
    runtime.bus.publish = lambda *args: (_ for _ in ()).throw(ConnectionError("offline"))
    with pytest.raises(ConnectionError):
        runtime.tasks.relay_once()
    with runtime.sessions() as session:
        from sqlalchemy import select

        assert session.scalar(select(Outbox)).sent_at is None
    assert runtime.tasks.get("owner", task["id"])["status"] == "pending"


def test_validation_origin_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["mode"] == "test"
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"username": "learner", "password": "ephemeral-password"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    headers = account(client)
    response = client.post("/api/v1/tasks", json={"prompt": " "}, headers=headers)
    assert response.status_code == 422
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert b"lab_http_requests_total" in client.get("/metrics").content


def test_state_machine_terminal():
    task = Task(status="succeeded")
    with pytest.raises(ValueError):
        transition(task, "running")
    assert set(TRANSITIONS) == {"pending", "ready", "running", "retry_wait", "succeeded", "failed"}


def test_transient_retry_budget_and_dlq(runtime):
    task, _ = enqueue(runtime)
    runtime.model.run = lambda task: (_ for _ in ()).throw(ConnectionError("temporary"))
    for attempt in range(runtime.settings.max_attempts):
        assert runtime.tasks.execute_once()
        with runtime.sessions() as session, session.begin():
            stored = session.get(Task, task["id"])
            assert stored.attempt_count == attempt + 1
            if attempt + 1 < runtime.settings.max_attempts:
                assert stored.status == "retry_wait"
                stored.next_attempt_at = 0
            else:
                assert stored.status == "failed"
        runtime.tasks.recover()
    assert not runtime.tasks.execute_once()
    runtime.tasks.relay_once()
    assert runtime.bus.messages[-1][1]["event_type"] == "task.failed"


def test_outbox_ack_window_republish_stable_id(runtime):
    from sqlalchemy import select

    runtime.tasks.create("owner", "key", "hello", "trace")
    runtime.tasks.relay_once()
    first = runtime.bus.messages[0][1]
    # Model process crash after Kafka acknowledgement before SQL sent_at commit.
    with runtime.sessions() as session, session.begin():
        session.scalar(select(Outbox)).sent_at = None
    runtime.tasks.relay_once()
    second = runtime.bus.messages[1][1]
    assert first["event_id"] == second["event_id"]
    assert runtime.tasks.receive(first)
    assert not runtime.tasks.receive(second)
    assert runtime.tasks.execute_once()
    assert not runtime.tasks.execute_once()


def test_same_owner_idempotency_concurrent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    runtime = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///" + str(tmp_path / "race.db")))
    migrate(runtime.engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: runtime.tasks.create("owner", "key", "hello", "trace"), range(8)))
    assert len({task["id"] for task in results}) == 1
    assert runtime.tasks.listing("owner", 20, 0)["total"] == 1


def test_migration_repeat_and_sqlite_guard(runtime):
    migrate(runtime.engine)
    with pytest.raises(ValueError):
        Settings(mode="production", database_url="sqlite+pysqlite:///:memory:")


def test_cache_aside_and_outage(runtime):
    class Cache:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def setex(self, key, ttl, value):
            self.values[key] = value

    runtime.cache.client = Cache()
    task, _ = enqueue(runtime)
    runtime.tasks.execute_once()
    assert runtime.tasks.document("owner", task["id"])["cache_status"] == "miss"
    assert runtime.tasks.document("owner", task["id"])["cache_status"] == "hit"
    runtime.cache.client.get = lambda key: (_ for _ in ()).throw(ConnectionError("down"))
    assert runtime.tasks.document("owner", task["id"])["cache_status"] == "unavailable"
    with pytest.raises(Exception) as caught:
        runtime.tasks.document("other", task["id"])
    assert caught.value.status == 404


def test_lifecycle_and_attempt_audit(runtime):
    task, _ = enqueue(runtime)
    runtime.tasks.execute_once()
    events = runtime.tasks.events("owner", task["id"])["items"]
    assert [row["kind"] for row in events] == ["pending", "outbox_sent", "ready", "running", "succeeded"]
    assert all(row["trace_id"] == "trace" and row["created_at"] for row in events)
    attempts = runtime.tasks.attempts("owner", task["id"])["items"]
    assert len(attempts) == 1 and attempts[0]["outcome"] == "succeeded"
    assert attempts[0]["finished_at"] is not None


def test_chunked_body_limit(client):
    def chunks():
        yield b'{"prompt":"'
        yield b"x" * 70000
        yield b'"}'

    response = client.post("/api/v1/tasks", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_username_normalization_and_invalid_config(client):
    account(client, "Learner")
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "LEARNER", "password": "ephemeral-password"}
        ).json()["user"]["username"]
        == "learner"
    )
    assert (
        client.post(
            "/api/v1/auth/register", json={"username": "learner", "password": "ephemeral-password"}
        ).status_code
        == 409
    )
    for kwargs in ({"model_mode": "typo"}, {"lease_seconds": 0}, {"max_attempts": 0}):
        with pytest.raises(ValueError):
            Settings(**kwargs)


def test_model_mode_change_never_calls_live(runtime, monkeypatch):
    from backend.adapters import Model

    task, _ = enqueue(runtime)
    runtime.tasks.model = Model(Settings(model_mode="live", live_enabled=True))
    called = []
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: called.append(True))
    runtime.tasks.execute_once()
    assert runtime.tasks.get("owner", task["id"])["status"] == "failed"
    assert not called


def test_http_errors_have_envelope(client):
    for response in (client.get("/not-a-route"), client.delete("/healthz")):
        assert response.status_code in {404, 405}
        assert "error" in response.json()
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_unexpected_error_sanitized_and_traced(runtime):
    from backend.app import create_app

    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    account(client)
    runtime.tasks.listing = lambda *args: (_ for _ in ()).throw(RuntimeError("private password"))
    response = client.get("/api/v1/tasks")
    assert response.status_code == 500
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert "private" not in response.text


def test_opaque_keys_preserve_case_and_space(runtime):
    ids = [runtime.tasks.create("owner", key, "hello", "trace")["id"] for key in ("abc", "ABC", "abc ")]
    assert len(set(ids)) == 3
    assert runtime.tasks.create("owner", "abc", "hello", "trace")["id"] == ids[0]
