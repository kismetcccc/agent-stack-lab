import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from confluent_kafka import Consumer, Producer
from conftest import completed, eventually, rows, submit

pytestmark = pytest.mark.integration


def test_full_chain_and_duplicate_event(user, stores):
    task = submit(user)
    task_id = task["id"]
    final = completed(user, task_id)
    assert final["model_mode"] == "deterministic"
    sql_task = rows(stores, "SELECT * FROM tasks WHERE id=:id", id=task_id)[0]
    assert sql_task["status"] == "succeeded" and sql_task["result_id"]
    outbox = rows(stores, "SELECT * FROM outbox WHERE task_id=:id", id=task_id)
    assert len(outbox) == 1 and outbox[0]["sent_at"] is not None
    event = json.loads(outbox[0]["payload"])
    assert rows(stores, "SELECT * FROM inbox WHERE event_id=:id", id=event["event_id"])
    attempts = rows(stores, "SELECT * FROM attempts WHERE task_id=:id", id=task_id)
    assert len(attempts) == 1 and attempts[0]["fence"] > 0
    cache_key = "progress:" + task_id
    assert stores["redis"].get(cache_key) == b"running"
    assert 0 < stores["redis"].ttl(cache_key) <= 300
    stores["redis"].delete(cache_key)
    assert user.get(f"/api/v1/tasks/{task_id}").json()["status"] == "succeeded"
    # Discover the configured collection without depending on an adapter implementation.
    documents = []
    for db_name in stores["mongo"].list_database_names():
        if db_name in {"admin", "config", "local"}:
            continue
        db = stores["mongo"][db_name]
        for name in db.list_collection_names():
            documents.extend(db[name].find({"_id": sql_task["result_id"]}))
    assert len(documents) == 1, "SQL success must reference a durable Mongo document"
    result_key = "result:" + sql_task["result_id"]
    stores["redis"].delete(result_key)
    result = user.get(f"/api/v1/tasks/{task_id}/results")
    assert result.json()["cache_status"] == "miss"
    assert 0 < stores["redis"].ttl(result_key) <= 300
    assert user.get(f"/api/v1/tasks/{task_id}/results").json()["cache_status"] == "hit"
    assert result.status_code == 200 and result.json()["content"]
    steps = user.get(f"/api/v1/tasks/{task_id}/events")
    assert steps.status_code == 200 and steps.json()["items"]
    kinds = {item["kind"] for item in steps.json()["items"]}
    assert {"pending", "outbox_sent", "ready", "running", "succeeded"} <= kinds
    assert len(rows(stores, "SELECT * FROM task_events WHERE task_id=:id", id=task_id)) >= 5
    attempt_dto = user.get(f"/api/v1/tasks/{task_id}/attempts")
    assert attempt_dto.status_code == 200 and len(attempt_dto.json()["items"]) == 1

    consumer = Consumer(
        {
            "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            "group.id": "evidence-" + uuid.uuid4().hex,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([os.getenv("KAFKA_TOPIC", "agent.tasks")])

    def find_event():
        message = consumer.poll(1)
        return (
            message and not message.error() and json.loads(message.value())["event_id"] == event["event_id"]
        )

    try:
        eventually(find_event, timeout=30)
    finally:
        consumer.close()
    producer = Producer({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"]})
    errors = []
    producer.produce(
        os.getenv("KAFKA_TOPIC", "agent.tasks"),
        key=task_id,
        value=json.dumps(event),
        on_delivery=lambda err, msg: errors.append(err) if err else None,
    )
    assert producer.flush(15) == 0 and not errors
    time.sleep(4)  # allow a complete consumer cycle before checking no extra execution
    assert len(rows(stores, "SELECT * FROM attempts WHERE task_id=:id", id=task_id)) == 1
    assert len(rows(stores, "SELECT * FROM inbox WHERE event_id=:id", id=event["event_id"])) == 1


def test_concurrent_idempotency_and_conflict(user, stores):
    key = uuid.uuid4().hex

    def send(prompt):
        return user.post("/api/v1/tasks", json={"prompt": prompt}, headers={"Idempotency-Key": key})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, ["same payload"] * 8))
    assert {r.status_code for r in responses} == {202}
    ids = {r.json()["id"] for r in responses}
    assert len(ids) == 1
    assert send("different payload").status_code == 409
    assert (
        len(
            rows(
                stores,
                "SELECT id FROM tasks WHERE idempotency_key=:key",
                key=hashlib.sha256(key.encode()).hexdigest(),
            )
        )
        == 1
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        key = uuid.uuid4().hex
        conflict = list(pool.map(send, ["payload A", "payload B"]))
    assert sorted(r.status_code for r in conflict) == [202, 409]
    for task_id in ids | {r.json()["id"] for r in conflict if r.status_code == 202}:
        completed(user, task_id)


def test_auth_csrf_ownership_and_safe_dtos(user, base_url):
    task = submit(user)
    completed(user, task["id"])
    with httpx.Client(base_url=base_url) as stranger:
        for suffix in ("", "/events", "/results", "/attempts"):
            assert stranger.get(f"/api/v1/tasks/{task['id']}{suffix}").status_code == 401
        response = stranger.post(
            "/api/v1/auth/register",
            json={"username": "other_" + uuid.uuid4().hex[:16], "password": "Other-only!password42"},
        )
        assert response.status_code in (200, 201)
        for suffix in ("", "/events", "/results", "/attempts"):
            assert stranger.get(f"/api/v1/tasks/{task['id']}{suffix}").status_code in (403, 404)
        assert (
            stranger.post(
                "/api/v1/tasks", json={"prompt": "no csrf"}, headers={"Idempotency-Key": uuid.uuid4().hex}
            ).status_code
            == 403
        )
    assert (
        user.post(
            "/api/v1/tasks",
            json={"prompt": "wrong origin"},
            headers={"Origin": "https://evil.invalid", "Idempotency-Key": uuid.uuid4().hex},
        ).status_code
        == 403
    )
    for forbidden in (
        "password_hash",
        "token_hash",
        "csrf_hash",
        "DATABASE_URL",
        "Traceback",
        "mysql+pymysql",
    ):
        assert forbidden not in json.dumps(task)
    assert user.post("/api/v1/auth/logout").status_code == 204
    assert user.get("/api/v1/auth/me").status_code == 401


def test_auth_rotation_expiration_validation_and_pagination(user, stores, base_url):
    from sqlalchemy import text

    from backend.service import digest

    previous = user.headers["X-CSRF-Token"]
    response = user.get("/api/v1/auth/me")
    assert response.status_code == 200 and response.headers.get("X-Request-ID")
    fresh = response.json()["csrf_token"]
    assert fresh != previous
    assert (
        user.post(
            "/api/v1/tasks", json={"prompt": "stale csrf"}, headers={"Idempotency-Key": uuid.uuid4().hex}
        ).status_code
        == 403
    )
    user.headers["X-CSRF-Token"] = fresh
    assert user.post("/api/v1/tasks", json={"prompt": "valid but missing key"}).status_code in (400, 422)
    assert (
        user.post(
            "/api/v1/tasks", json={"prompt": "x" * 10001}, headers={"Idempotency-Key": uuid.uuid4().hex}
        ).status_code
        == 422
    )
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert user.get("/api/v1/tasks?" + query).status_code == 422
    assert user.get("/api/v1/tasks?limit=1&offset=0").json()["items"] == []
    token = user.cookies.get("lab_session")
    stored = rows(stores, "SELECT * FROM sessions WHERE token_hash=:hash", hash=digest(token))[0]
    assert stored["token_hash"] != token and stored["csrf_hash"] != fresh
    with stores["sql"].begin() as conn:
        conn.execute(text("UPDATE sessions SET expires_at=0 WHERE token_hash=:hash"), {"hash": digest(token)})
    assert user.get("/api/v1/auth/me").status_code == 401
    assert user.get("/api/v1/tasks").status_code == 401
    assert (
        user.post(
            "/api/v1/tasks", json={"prompt": "expired"}, headers={"Idempotency-Key": uuid.uuid4().hex}
        ).status_code
        == 401
    )
    with httpx.Client(base_url=base_url) as unauth:
        assert unauth.get("/api/v1/tasks").status_code == 401
        assert (
            unauth.post(
                "/api/v1/tasks", json={"prompt": "anonymous"}, headers={"Idempotency-Key": uuid.uuid4().hex}
            ).status_code
            == 401
        )


def test_idempotency_keys_are_byte_exact_not_mysql_collation(user, stores):
    prefix = uuid.uuid4().hex
    keys = [prefix + "Case", prefix + "case"]
    tasks = [submit(user, prompt="case-sensitive key", key=key) for key in keys]
    assert len({task["id"] for task in tasks}) == 2
    for task in tasks:
        completed(user, task["id"])
