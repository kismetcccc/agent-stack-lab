"""Finite real service fault/restart assertions, orchestrated by the host script.

Only synthetic CI teaching records are used. Private session state is mode 0600,
never printed, never included in artifacts, and removed by the host exit trap.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://api:8000")
BASE = "/api/v1/lab"
STATE = Path("/reports/playground-state.json")


def save(state):
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(state, handle)


def checked(response, status=200):
    assert response.status_code == status, f"expected HTTP {status}; no response body logged"
    return response.json() if status != 204 else None


def error(response, code):
    body = checked(response, 503)
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["request_id"] == response.headers.get("X-Request-ID")
    for forbidden in ("Traceback", "sqlalchemy", "pymysql", "password_hash", "token_hash", "mongodb://", "redis://"):
        assert forbidden not in response.text, "unsafe dependency error detail"


def wait_received(client, message_id, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = checked(client.get(f"{BASE}/kafka/messages/{message_id}"))
        if item["consumer"]["status"] == "received":
            return item
        time.sleep(0.5)
    raise AssertionError("actual Kafka consumer receipt not observed before deadline")


def run(action):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    with httpx.Client(
        base_url=BASE_URL, timeout=45, cookies=state.get("cookies", {}),
        headers={"X-CSRF-Token": state.get("csrf", "")},
    ) as client:
        if action == "prepare":
            assert not state, "refusing to overwrite an existing private probe state"
            auth = checked(client.post("/api/v1/auth/register", json={
                "username": "lab_fault_" + uuid.uuid4().hex[:16], "password": "Synthetic-fault!" + uuid.uuid4().hex,
            }), 201)
            state.update(cookies=dict(client.cookies), csrf=auth["csrf_token"])
            client.headers["X-CSRF-Token"] = auth["csrf_token"]
            state["mysql"] = checked(client.post(f"{BASE}/mysql/records", json={
                "name": "persistent-fault-" + uuid.uuid4().hex[:12], "value": "synthetic retained teaching record",
            }), 201)
            state["mongo"] = checked(client.post(f"{BASE}/mongo/documents", json={
                "document": {"probe": "synthetic stored document", "nested": {"retained": True}},
            }), 201)
            state["redis_key"] = "fault_" + uuid.uuid4().hex
            checked(client.put(f"{BASE}/redis/keys/{state['redis_key']}", json={"value": "real-redis", "ttl_seconds": 3600}))
            state["kafka_payload"] = {"id": str(uuid.uuid4()), "key": "fault-probe", "value": "sent while Worker is stopped"}
        elif action == "mysql-unavailable":
            path = f"{BASE}/mysql/records/{state['mysql']['id']}"
            error(client.get(path), "database_unavailable")
            error(client.post(f"{BASE}/mysql/records", json={"name": "blocked", "value": "not accepted"}), "database_unavailable")
        elif action == "mysql-restored":
            assert checked(client.get(f"{BASE}/mysql/records/{state['mysql']['id']}")) == state["mysql"]
        elif action == "redis-unavailable":
            path = f"{BASE}/redis/keys/{state['redis_key']}"
            error(client.get(path), "redis_unavailable")
            error(client.put(path, json={"value": "must not fake success", "ttl_seconds": 60}), "redis_unavailable")
            error(client.delete(path + "?confirm=true"), "redis_unavailable")
        elif action == "mongo-unavailable":
            path = f"{BASE}/mongo/documents/{state['mongo']['id']}"
            error(client.get(path), "document_unavailable")
            error(client.get(f"{BASE}/mongo/documents"), "document_unavailable")
            error(client.put(path, json={"document": {"not": "saved"}}), "document_unavailable")
            error(client.delete(path + "?confirm=true"), "document_unavailable")
        elif action == "kafka-unavailable":
            payload = {"id": str(uuid.uuid4()), "key": "unconfirmed-probe", "value": "broker unavailable"}
            # Save the ID before the request: a timeout is not evidence of nondelivery.
            state["unconfirmed_payload"] = payload
            save(state)
            error(client.post(f"{BASE}/kafka/messages", json=payload), "kafka_publish_unconfirmed")
            item = checked(client.get(f"{BASE}/kafka/messages/{payload['id']}"))
            assert item["producer"]["status"] == "unconfirmed"
            for field in ("acknowledged_at", "partition", "offset"):
                assert item["producer"][field] is None
            assert item["consumer"]["status"] == "not_observed"
            # The same ID queries the durable attempt; it must not silently send again.
            replay = checked(client.post(f"{BASE}/kafka/messages", json=payload), 200)
            assert replay["producer"] == item["producer"] and replay["consumer"] == item["consumer"]
        elif action == "kafka-send-paused":
            item = checked(client.post(f"{BASE}/kafka/messages", json=state["kafka_payload"]), 202)
            assert item["producer"]["status"] == "acknowledged"
            assert item["consumer"]["status"] == "not_observed", "producer ACK is not a consumer receipt"
            for field in ("received_at", "partition", "offset", "key", "value"):
                assert item["consumer"][field] is None
            state["ack"] = item["producer"]
            # A real later read must still show no receipt while the only Worker is stopped.
            time.sleep(1)
            later = checked(client.get(f"{BASE}/kafka/messages/{item['id']}"))
            assert later["consumer"]["status"] == "not_observed"
        elif action == "kafka-received":
            item = wait_received(client, state["kafka_payload"]["id"])
            assert item["producer"] == state["ack"]
            receipt = item["consumer"]
            assert receipt["key"] == state["kafka_payload"]["key"]
            assert receipt["value"] == state["kafka_payload"]["value"]
            assert receipt["group"] == "agent-lab-observer-v1"
            for field in ("partition", "offset"):
                assert receipt[field] == item["producer"][field]
            state["receipt"] = receipt
        elif action == "restart-stable":
            item = wait_received(client, state["kafka_payload"]["id"])
            assert item["producer"] == state["ack"] and item["consumer"] == state["receipt"]
            # Direct CRUD state must still be present after the service outage cycle.
            assert checked(client.get(f"{BASE}/mysql/records/{state['mysql']['id']}")) == state["mysql"]
            assert checked(client.get(f"{BASE}/mongo/documents/{state['mongo']['id']}")) == state["mongo"]
            redis = checked(client.get(f"{BASE}/redis/keys/{state['redis_key']}"))
            assert redis["exists"] is True and redis["value"] == "real-redis" and redis["ttl_ms"] > 0
        elif action == "cleanup":
            for path in (
                f"mysql/records/{state['mysql']['id']}", f"mongo/documents/{state['mongo']['id']}",
                f"redis/keys/{state['redis_key']}",
            ):
                checked(client.delete(f"{BASE}/{path}?confirm=true"), 204)
        else:
            raise AssertionError("unknown playground fault probe action")
    save(state)
    print("PASS: real component playground " + action)


if __name__ == "__main__":
    run(sys.argv[1])
