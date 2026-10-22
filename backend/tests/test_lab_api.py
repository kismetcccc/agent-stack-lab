"""Offline API tests with SQLite and explicitly named in-memory lab substitutes."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.app import create_app
from backend.config import Settings
from backend.db import LabKafkaMessage, LabRecord, Task
from backend.lab_adapters import RedisLabKV
from backend.migrate import migrate
from backend.runtime import Runtime

ID = "11111111-1111-4111-8111-111111111111"
PREFIX = "/api/v1/lab"
WRITES = [
    ("POST", "/mysql/records", {"name": "sample", "value": ""}),
    ("PUT", f"/mysql/records/{ID}", {"name": "sample", "value": ""}),
    ("DELETE", f"/mysql/records/{ID}?confirm=true", None),
    ("PUT", "/redis/keys/sample", {"value": "", "ttl_seconds": 1}),
    ("DELETE", "/redis/keys/sample?confirm=true", None),
    ("POST", "/mongo/documents", {"document": {}}),
    ("PUT", f"/mongo/documents/{ID}", {"document": {}}),
    ("DELETE", f"/mongo/documents/{ID}?confirm=true", None),
    ("POST", "/kafka/messages", {"id": ID, "key": "sample", "value": "hello"}),
]
READS = [
    "/mysql/records", f"/mysql/records/{ID}", "/redis/keys/sample",
    "/mongo/documents", f"/mongo/documents/{ID}", "/kafka/messages", f"/kafka/messages/{ID}",
]


@pytest.fixture(scope="module")
def runtime():
    value = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///:memory:"))
    migrate(value.engine)
    yield value
    value.engine.dispose()


@pytest.fixture(scope="module")
def app(runtime):
    return create_app(runtime)


def register(client):
    response = client.post("/api/v1/auth/register", json={
        "username": "learner_" + uuid4().hex[:12], "password": "Synthetic-lab-tests-only!",
    })
    assert response.status_code == 201
    return {"X-CSRF-Token": response.json()["csrf_token"]}, response.json()["user"]["id"]


@pytest.fixture(scope="module")
def authed(app):
    with TestClient(app) as client:
        headers, owner = register(client)
        yield client, headers, owner


@pytest.mark.parametrize("method,path,body", WRITES + [("GET", path, None) for path in READS])
def test_all_lab_routes_require_existing_session(app, method, path, body):
    with TestClient(app) as client:
        response = client.request(method, PREFIX + path, json=body)
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("method,path,body", WRITES)
def test_every_lab_write_requires_csrf(authed, method, path, body):
    client, _, _ = authed
    response = client.request(method, PREFIX + path, json=body)
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"


@pytest.mark.parametrize("path", ["/mysql/records", "/mongo/documents", "/kafka/messages"])
@pytest.mark.parametrize("query", ["limit=0", "limit=51", "offset=-1", "offset=10001"])
def test_lab_lists_have_bounded_pagination(authed, path, query):
    client, _, _ = authed
    assert client.get(PREFIX + path + "?" + query).status_code == 422


@pytest.mark.parametrize("path", ["/mysql/records", "/mongo/documents", "/kafka/messages"])
def test_uuid_and_absent_object_errors_are_controlled(authed, path):
    client, _, _ = authed
    assert client.get(PREFIX + path + "/not-uuid").status_code == 422
    response = client.get(PREFIX + path + "/" + str(uuid4()))
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", [f"/mysql/records/{ID}", "/redis/keys/sample", f"/mongo/documents/{ID}"])
@pytest.mark.parametrize("query", ["", "?confirm=false"])
def test_delete_requires_explicit_confirmation_before_touching_storage(authed, path, query):
    client, headers, _ = authed
    response = client.delete(PREFIX + path + query, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "confirmation_required"


def test_shared_records_crud_and_original_task_ownership(app, runtime, authed):
    client, headers, owner = authed
    mysql = client.post(PREFIX + "/mysql/records", json={"name": "  shared  ", "value": "original"}, headers=headers)
    mongo = client.post(PREFIX + "/mongo/documents", json={"document": {"_id": "data", "keep": True}}, headers=headers)
    assert mysql.status_code == mongo.status_code == 201
    sql_row, doc_row = mysql.json(), mongo.json()
    assert sql_row["name"] == "shared"
    task = runtime.tasks.create(owner, str(uuid4()), "original private task", "trace")
    with TestClient(app) as other:
        other_headers, _ = register(other)
        for path, row in (("/mysql/records", sql_row), ("/mongo/documents", doc_row)):
            assert other.get(PREFIX + path + "/" + row["id"]).json() == row
            assert row["id"] in {item["id"] for item in other.get(PREFIX + path).json()["items"]}
        updated_sql = other.put(PREFIX + "/mysql/records/" + sql_row["id"],
                                json={"name": "new", "value": ""}, headers=other_headers).json()
        updated_doc = other.put(PREFIX + "/mongo/documents/" + doc_row["id"],
                                json={"document": {"replacement": [1, "<b>text</b>"]}}, headers=other_headers).json()
        assert updated_sql["created_at"] == sql_row["created_at"] and updated_sql["value"] == ""
        assert updated_doc["created_at"] == doc_row["created_at"] and "keep" not in updated_doc["document"]
        assert client.get(PREFIX + "/mongo/documents/" + doc_row["id"]).json() == updated_doc
        for suffix in ("", "/events", "/attempts", "/results", "/agent-steps"):
            assert other.get("/api/v1/tasks/" + task["id"] + suffix).status_code == 404
        for path, row in (("/mysql/records", sql_row), ("/mongo/documents", doc_row)):
            target = PREFIX + path + "/" + row["id"]
            assert other.delete(target + "?confirm=true", headers=other_headers).status_code == 204
            assert client.get(target).status_code == 404
            assert other.delete(target + "?confirm=true", headers=other_headers).status_code == 404
    with runtime.sessions() as session:
        assert session.get(Task, task["id"]) is not None
        assert session.get(LabRecord, sql_row["id"]) is None
    assert "owner_id" not in LabRecord.__table__.c and "owner_id" not in LabKafkaMessage.__table__.c


def test_shared_redis_empty_value_expiry_delete_and_no_task_cache_access(app, runtime, authed):
    client, headers, _ = authed
    clock = [100.0]
    runtime.lab.kv.clock = lambda: clock[0]
    target = PREFIX + "/redis/keys/shared_key"
    response = client.put(target, json={"value": "", "ttl_seconds": 2}, headers=headers)
    assert response.status_code == 200
    assert response.json()["exists"] and response.json()["value"] == "" and response.json()["ttl_ms"] == 2000
    with TestClient(app) as other:
        other_headers, _ = register(other)
        clock[0] += 1
        assert other.get(target).json()["ttl_ms"] == 1000
        clock[0] += 1
        missing = other.get(target).json()
        assert missing["exists"] is False and missing["value"] is None and missing["ttl_ms"] == -2
        assert other.delete(target + "?confirm=true", headers=other_headers).status_code == 204
    assert client.get(PREFIX + "/redis/keys/result:secret").status_code == 422
    assert client.get(PREFIX + "/redis/keys").status_code == 404


@pytest.mark.parametrize("document", [{"n": float("nan")}, {"n": float("inf")}, {"n": 2**63}, {"n": -(2**63) - 1}, {"x": "\ud800"}])
def test_mongo_json_invalid_numbers_and_unicode_return_422_without_store(authed, runtime, monkeypatch, document):
    client, headers, _ = authed
    called = []
    monkeypatch.setattr(runtime.lab.documents, "create", lambda row: called.append(row))
    response = client.post(PREFIX + "/mongo/documents", content=json.dumps({"document": document}),
                           headers=headers | {"Content-Type": "application/json"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"
    assert not called


def test_origin_body_limit_unknown_fields_and_request_id(authed):
    client, headers, _ = authed
    response = client.post(PREFIX + "/mysql/records", json={"name": "ok", "value": ""},
                           headers=headers | {"Origin": "https://not-local.example"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "origin_forbidden"
    response = client.post(PREFIX + "/mysql/records", json={"name": "ok", "value": "", "sql": "no"}, headers=headers)
    assert response.status_code == 422
    assert response.json()["request_id"] == response.headers["x-request-id"]
    response = client.post(PREFIX + "/mongo/documents", content=b"x" * 65537, headers=headers)
    assert response.status_code == 413


def fail(*args, **kwargs):
    raise ConnectionError("private-connection-and-password")


@pytest.mark.parametrize("operation,method,path,body", [
    ("listing", "GET", "/mongo/documents", None),
    ("get", "GET", f"/mongo/documents/{ID}", None),
    ("create", "POST", "/mongo/documents", {"document": {}}),
    ("replace", "PUT", f"/mongo/documents/{ID}", {"document": {}}),
    ("delete", "DELETE", f"/mongo/documents/{ID}?confirm=true", None),
])
def test_mongo_failures_are_sanitized_not_empty_success(authed, runtime, monkeypatch, operation, method, path, body):
    client, headers, _ = authed
    monkeypatch.setattr(runtime.lab.documents, operation, fail)
    response = client.request(method, PREFIX + path, json=body, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "document_unavailable"
    assert "private" not in response.text


def test_mongo_write_must_really_read_back_not_echo(authed, runtime, monkeypatch):
    client, headers, _ = authed
    monkeypatch.setattr(runtime.lab.documents, "get", lambda _: None)
    response = client.post(PREFIX + "/mongo/documents", json={"document": {"cannot": "echo"}}, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "document_unavailable"


@pytest.mark.parametrize("method,body", [("GET", None), ("PUT", {"value": "test", "ttl_seconds": 1}), ("DELETE", None)])
def test_unconfigured_redis_never_degrades_to_fake_success(authed, runtime, monkeypatch, method, body):
    client, headers, _ = authed
    monkeypatch.setattr(runtime.lab, "kv", RedisLabKV(None))
    response = client.request(method, PREFIX + "/redis/keys/sample?confirm=true", json=body, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "redis_unavailable"


def test_sql_storage_failure_is_safe_and_does_not_publish(authed, runtime, monkeypatch):
    client, headers, _ = authed
    calls = []
    monkeypatch.setattr(runtime.lab.messages, "publish", lambda event: calls.append(event))

    def unavailable():
        raise SQLAlchemyError("private SQL credentials")

    monkeypatch.setattr(runtime.lab, "sessions", unavailable)
    response = client.post(PREFIX + "/kafka/messages", json={"id": str(uuid4()), "key": "safe", "value": "hello"}, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "database_unavailable"
    assert "private" not in response.text and not calls


def test_kafka_routes_idempotency_shared_visibility_and_no_admin(app, runtime, authed, monkeypatch):
    client, headers, _ = authed
    body = {"id": str(uuid4()), "key": "shared", "value": "Kafka independent"}
    initial_count = len(runtime.lab.messages.messages)
    response = client.post(PREFIX + "/kafka/messages", json=body, headers=headers)
    assert response.status_code == 202
    snapshot = response.json()
    assert snapshot["producer"]["status"] == "acknowledged" and snapshot["consumer"]["status"] == "not_observed"
    assert snapshot["consumer"]["value"] is None and snapshot["consumer"]["offset"] is None
    with TestClient(app) as other:
        other_headers, _ = register(other)
        repeated = other.post(PREFIX + "/kafka/messages", json=body, headers=other_headers)
        assert repeated.status_code == 200 and repeated.json()["id"] == body["id"]
        assert other.get(PREFIX + "/kafka/messages/" + body["id"]).status_code == 200
        conflict = other.post(PREFIX + "/kafka/messages", json=body | {"value": "different"}, headers=other_headers)
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "message_id_conflict"
    assert len(runtime.lab.messages.messages) == initial_count + 1
    monkeypatch.setattr(runtime.lab.messages, "publish", fail)
    uncertain = body | {"id": str(uuid4())}
    response = client.post(PREFIX + "/kafka/messages", json=uncertain, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "kafka_publish_unconfirmed"
    snapshot = client.get(PREFIX + "/kafka/messages/" + uncertain["id"]).json()
    assert snapshot["producer"]["status"] == "unconfirmed" and snapshot["producer"]["offset"] is None
    assert client.post(PREFIX + "/kafka/messages", json=uncertain, headers=headers).status_code == 200
    assert client.delete(PREFIX + "/kafka/messages/" + body["id"] + "?confirm=true", headers=headers).status_code == 405
    assert client.post(PREFIX + "/kafka/topics", json={}, headers=headers).status_code == 404


def test_openapi_exposes_all_lab_dtos_and_null_observations(app):
    schema = app.openapi()
    assert {path.removeprefix(PREFIX) for path in schema["paths"] if path.startswith(PREFIX)} == {
        "/mysql/records", "/mysql/records/{record_id}", "/redis/keys/{key}",
        "/mongo/documents", "/mongo/documents/{document_id}",
        "/kafka/messages", "/kafka/messages/{message_id}",
    }
    assert schema["components"]["schemas"]["KafkaInput"]["additionalProperties"] is False
    assert set(schema["components"]["schemas"]["ConsumerView"]["required"]) == {
        "status", "received_at", "group", "partition", "offset", "key", "value",
    }


def test_persisted_order_pagination_and_duplicate_record_names(runtime):
    # Dedicated rows with the same timestamp make the id tiebreaker observable.
    with runtime.sessions() as session, session.begin():
        for suffix in range(3):
            session.add(LabRecord(
                id=f"ffffffff-ffff-4fff-8fff-{suffix:012d}", name="same allowed name", value=str(suffix),
                created_at=9999999999.0, updated_at=9999999999.0,
            ))
    listing = runtime.lab.mysql_list(2, 1)
    assert listing["limit"] == 2 and listing["offset"] == 1
    assert [row["value"] for row in listing["items"]] == ["1", "0"]
    for suffix in range(3):
        runtime.lab.mysql_delete(f"ffffffff-ffff-4fff-8fff-{suffix:012d}")


def test_mongo_put_requires_successful_readback_not_request_echo(authed, runtime, monkeypatch):
    client, headers, _ = authed
    row = runtime.lab.mongo_create({"before": True})
    monkeypatch.setattr(runtime.lab.documents, "get", lambda _: None)
    response = client.put(PREFIX + "/mongo/documents/" + row["id"], json={"document": {"after": True}}, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "document_unavailable"
