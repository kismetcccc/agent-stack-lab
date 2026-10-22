"""Independent real-store playground acceptance; shared data, authenticated access.

No fake SQL/cache/document/broker adapters are accepted. Existing task ownership
and chain cases remain in their original suites; these are separate lab records.
"""

import json
import os
import uuid

import httpx
import pytest
from confluent_kafka import Consumer
from conftest import eventually, rows
from test_api_contract import assert_error

pytestmark = pytest.mark.integration
BASE = "/api/v1/lab"
TOPIC = "agent.lab.messages.v1"
GROUP = "agent-lab-observer-v1"


@pytest.fixture
def other_user(base_url):
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post("/api/v1/auth/register", json={
            "username": "shared_lab_" + uuid.uuid4().hex[:16], "password": "Synthetic-shared-lab!42",
        })
        assert response.status_code == 201
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client


def checked(response, status=200):
    assert response.status_code == status, "unexpected HTTP status for real lab operation"
    return response.json()


def test_mysql_crud_persists_real_shared_records_without_tasks(user, other_user, stores):
    payload = {"name": "  MySQL-" + uuid.uuid4().hex[:12] + "  ", "value": "literal teaching value"}
    created = checked(user.post(f"{BASE}/mysql/records", json=payload), 201)
    path = f"{BASE}/mysql/records/{created['id']}"
    try:
        assert set(created) == {"id", "name", "value", "created_at", "updated_at"}
        assert created["name"] == payload["name"].strip() and created["value"] == payload["value"]
        stored = rows(stores, "SELECT * FROM lab_records WHERE id=:id", id=created["id"])
        assert len(stored) == 1 and stored[0]["name"] == created["name"]
        assert stored[0]["value"] == created["value"]
        assert checked(other_user.get(path)) == created, "personal lab data must not be partitioned by account"
        listing = checked(other_user.get(f"{BASE}/mysql/records?limit=50&offset=0"))
        assert set(listing) == {"items", "total", "limit", "offset"}
        assert listing["limit"] == 50 and listing["offset"] == 0
        assert created in listing["items"]
        changed = checked(other_user.put(path, json={"name": created["name"], "value": "updated by second login"}))
        assert checked(user.get(path)) == changed
        assert changed["created_at"] == created["created_at"]
        assert rows(stores, "SELECT value FROM lab_records WHERE id=:id", id=created["id"])[0]["value"] == changed["value"]
        assert not rows(stores, "SELECT id FROM tasks WHERE id=:id", id=created["id"])
        assert not rows(stores, "SELECT id FROM outbox WHERE task_id=:id", id=created["id"])
        assert_error(user.delete(path), 422)
        assert_error(user.delete(path + "?confirm=false"), 422)
        assert checked(user.get(path))["value"] == changed["value"]
        assert other_user.delete(path + "?confirm=true").status_code == 204
        assert not rows(stores, "SELECT id FROM lab_records WHERE id=:id", id=created["id"])
        assert_error(user.get(path), 404)
        assert_error(user.put(path, json={"name": "missing", "value": ""}), 404)
        assert_error(user.delete(path + "?confirm=true"), 404)
    finally:
        user.delete(path + "?confirm=true")


def test_redis_real_value_pttl_expiry_and_shared_delete(user, other_user, stores):
    key = "ci_" + uuid.uuid4().hex
    path = f"{BASE}/redis/keys/{key}"
    physical = "lab:kv:" + key
    try:
        absent = checked(user.get(path))
        assert absent["key"] == key and absent["exists"] is False
        assert absent["value"] is None and absent["ttl_ms"] == -2
        value = "真实 Redis 值 <script>literal</script>"
        saved = checked(user.put(path, json={"value": value, "ttl_seconds": 2}))
        assert saved["exists"] is True and saved["value"] == value and 0 < saved["ttl_ms"] <= 2000
        assert stores["redis"].get(physical) == value.encode()
        assert 0 < stores["redis"].pttl(physical) <= 2000
        shared = checked(other_user.get(path))
        assert shared["value"] == value and 0 < shared["ttl_ms"] <= saved["ttl_ms"]

        def expired():
            result = checked(user.get(path))
            return result if result["exists"] is False else None

        expired_value = eventually(expired, timeout=10)
        assert expired_value["value"] is None and expired_value["ttl_ms"] == -2
        assert stores["redis"].get(physical) is None and stores["redis"].pttl(physical) == -2
        checked(other_user.put(path, json={"value": "second login", "ttl_seconds": 60}))
        assert checked(user.get(path))["value"] == "second login"
        reset = checked(user.put(path, json={"value": "overwritten", "ttl_seconds": 120}))
        assert reset["value"] == "overwritten" and 60000 < reset["ttl_ms"] <= 120000
        assert stores["redis"].get(physical) == b"overwritten"
        # Only this synthetic namespaced key is altered directly to prove the
        # API reports PTTL=-1 truthfully rather than claiming it expired.
        stores["redis"].persist(physical)
        without_expiry = checked(user.get(path))
        assert without_expiry["exists"] is True and without_expiry["ttl_ms"] == -1
        assert_error(user.delete(path), 422)
        assert stores["redis"].exists(physical) == 1
        assert user.delete(path + "?confirm=true").status_code == 204
        assert stores["redis"].exists(physical) == 0
        assert user.delete(path + "?confirm=true").status_code == 204
    finally:
        user.delete(path + "?confirm=true")


def test_mongo_json_crud_is_real_shared_and_replaces_only_lab_document(user, other_user, stores):
    document = {"title": "Mongo " + uuid.uuid4().hex[:12], "items": [1, True, None, {"note": "中文"}]}
    created = checked(user.post(f"{BASE}/mongo/documents", json={"document": document}), 201)
    path = f"{BASE}/mongo/documents/{created['id']}"
    collection = stores["mongo"].agent_lab.lab_documents
    try:
        assert set(created) == {"id", "document", "created_at", "updated_at"}
        assert created["document"] == document
        stored = collection.find_one({"_id": created["id"]})
        assert stored and stored["document"] == document
        assert stores["mongo"].agent_lab.results.find_one({"_id": created["id"]}) is None
        assert checked(other_user.get(path)) == created
        assert created in checked(other_user.get(f"{BASE}/mongo/documents?limit=50"))["items"]
        replacement = {"changed": {"count": 2}, "literal": '<img src=x onerror="window.__labXss=1">'}
        changed = checked(other_user.put(path, json={"document": replacement}))
        assert changed["document"] == replacement and changed["created_at"] == created["created_at"]
        assert collection.find_one({"_id": created["id"]})["document"] == replacement
        assert checked(user.get(path)) == changed
        assert_error(user.delete(path), 422)
        assert collection.find_one({"_id": created["id"]}) is not None
        assert other_user.delete(path + "?confirm=true").status_code == 204
        assert collection.find_one({"_id": created["id"]}) is None
        assert_error(user.get(path), 404)
        assert_error(user.put(path, json={"document": {}}), 404)
        assert_error(user.delete(path + "?confirm=true"), 404)
    finally:
        user.delete(path + "?confirm=true")


def test_kafka_ack_and_actual_receipt_match_broker_without_task_outbox(user, other_user, stores):
    payload = {"id": str(uuid.uuid4()), "key": "ci_" + uuid.uuid4().hex[:12], "value": "真实 Kafka 消息"}
    sent = checked(user.post(f"{BASE}/kafka/messages", json=payload), 202)
    path = f"{BASE}/kafka/messages/{payload['id']}"
    assert sent["id"] == payload["id"] and sent["topic"] == TOPIC
    assert sent["producer"]["status"] == "acknowledged"
    assert sent["producer"]["acknowledged_at"] and sent["producer"]["partition"] >= 0
    assert sent["producer"]["offset"] >= 0

    def observed():
        item = checked(other_user.get(path))
        return item if item["consumer"]["status"] == "received" else None

    received = eventually(observed, timeout=45)
    consumer_fact = received["consumer"]
    assert consumer_fact["group"] == GROUP and consumer_fact["received_at"]
    assert consumer_fact["key"] == payload["key"] and consumer_fact["value"] == payload["value"]
    for field in ("partition", "offset"):
        assert consumer_fact[field] == sent["producer"][field]
    # Independently observe the real broker message, not just an HTTP claim.
    consumer = Consumer({
        "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        "group.id": "lab-acceptance-" + uuid.uuid4().hex,
        "auto.offset.reset": "earliest", "enable.auto.commit": False,
    })
    consumer.subscribe([TOPIC])

    def matching_message():
        message = consumer.poll(1)
        if message is None or message.error():
            return None
        body = json.loads(message.value())
        return message if body.get("id") == payload["id"] else None

    try:
        message = eventually(matching_message, timeout=30)
        assert json.loads(message.value()) == {"schema_version": 1, **payload}
        assert message.key().decode() == payload["key"]
        assert message.partition() == consumer_fact["partition"]
        assert message.offset() == consumer_fact["offset"]
    finally:
        consumer.close()
    stored = rows(stores, "SELECT * FROM lab_kafka_messages WHERE id=:id", id=payload["id"])
    assert len(stored) == 1 and stored[0]["consumer_offset"] == consumer_fact["offset"]
    duplicate = checked(user.post(f"{BASE}/kafka/messages", json=payload))
    assert duplicate["producer"] == received["producer"] and duplicate["consumer"] == consumer_fact
    conflict = user.post(f"{BASE}/kafka/messages", json={**payload, "value": "different"})
    assert_error(conflict, 409)
    assert conflict.json()["error"]["code"] == "message_id_conflict"
    assert received["id"] in [item["id"] for item in checked(other_user.get(f"{BASE}/kafka/messages?limit=50"))["items"]]
    assert not rows(stores, "SELECT id FROM tasks WHERE id=:id", id=payload["id"])
    assert not rows(stores, "SELECT id FROM outbox WHERE task_id=:id", id=payload["id"])


def test_playground_auth_csrf_validation_and_no_raw_admin_surface(user, base_url):
    reads = ("mysql/records", "redis/keys/synthetic", "mongo/documents", "kafka/messages")
    writes = (
        ("post", "mysql/records", {"name": "safe", "value": ""}),
        ("put", "redis/keys/synthetic", {"value": "safe", "ttl_seconds": 60}),
        ("post", "mongo/documents", {"document": {"safe": True}}),
        ("post", "kafka/messages", {"id": str(uuid.uuid4()), "key": "safe", "value": "safe"}),
    )
    with httpx.Client(base_url=base_url, timeout=20) as anonymous:
        for route in reads:
            assert_error(anonymous.get(f"{BASE}/{route}"), 401)
        for method, route, payload in writes:
            assert_error(getattr(anonymous, method)(f"{BASE}/{route}", json=payload), 401)
            assert_error(getattr(user, method)(f"{BASE}/{route}", json=payload, headers={"X-CSRF-Token": "invalid"}), 403)
            assert_error(getattr(user, method)(f"{BASE}/{route}", json=payload, headers={"Origin": "https://evil.invalid"}), 403)
    for route in ("mysql/records", "mongo/documents", "kafka/messages"):
        for query in ("limit=0", "limit=51", "offset=-1", "offset=10001"):
            assert_error(user.get(f"{BASE}/{route}?{query}"), 422)
    for payload in ({"name": " ", "value": ""}, {"name": "x", "value": "x" * 1001}, {"name": "x", "value": "", "sql": "SELECT 1"}):
        assert_error(user.post(f"{BASE}/mysql/records", json=payload), 422)
    for ttl in (0, 3601, 1.5, True):
        assert_error(user.put(f"{BASE}/redis/keys/synthetic", json={"value": "x", "ttl_seconds": ttl}), 422)
    for key in ("result:private", "a.b", "中文", "x" * 65):
        assert_error(user.get(f"{BASE}/redis/keys/{key}"), 422)
    for document in ([], {"$set": 1}, {"nested": {"bad.key": 1}}, {"nul\x00": 1}, {"big": "中" * 6000}):
        assert_error(user.post(f"{BASE}/mongo/documents", json={"document": document}), 422)
    assert_error(user.post(f"{BASE}/kafka/messages", json={"id": str(uuid.uuid4()), "key": "safe", "value": "x", "topic": "agent.tasks"}), 422)
    for raw in ("mysql/query", "redis/command", "mongo/command", "kafka/topics"):
        assert_error(user.post(f"{BASE}/{raw}", json={}), 404)
