"""Frozen v1 -> v2 acceptance. Run ONLY before API/Worker in an empty CI database.

This suite never drops databases/tables or clears existing application data. The
explicit flags AND the empty-schema check prevent use against a running stack.
"""

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, event, inspect, text

pytestmark = pytest.mark.integration
LEGACY_TABLES = ("users", "sessions", "tasks", "outbox", "inbox", "attempts", "task_events")
USER_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"
ATTEMPT_ID = "44444444-4444-4444-8444-444444444444"
TRACE_ID = "55555555-5555-4555-8555-555555555555"
USERNAME = "ci_frozen_v1_user"
PASSWORD = "Synthetic-v1-only!42-password"
SESSION = "synthetic-ci-v1-session-never-a-real-secret"
CSRF = "synthetic-ci-v1-csrf-never-a-real-secret"
PROMPT = "Synthetic legacy task retained by the additive v2 migration"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def engine_for_fixture():
    assert os.getenv("CI") == "true" and os.getenv("LAB_CI_EPHEMERAL_SCHEMA") == "1", (
        "legacy fixture requires explicit CI-only opt-in; never run against a user's stack"
    )
    url = os.environ["DATABASE_URL"]
    assert url.startswith("mysql+pymysql://"), "upgrade acceptance requires real MySQL"
    return create_engine(url, pool_pre_ping=True)


def snapshot(engine):
    with engine.connect() as conn:
        return {
            name: [dict(row) for row in conn.execute(text(f"SELECT * FROM {name}")).mappings()]
            for name in LEGACY_TABLES
        }


def legacy_definitions(engine):
    with engine.connect() as conn:
        return {name: conn.exec_driver_sql(f"SHOW CREATE TABLE {name}").one()[1] for name in LEGACY_TABLES}


def insert(conn, table, values):
    fields = ",".join(values)
    binds = ",".join(":" + key for key in values)
    conn.execute(text(f"INSERT INTO {table} ({fields}) VALUES ({binds})"), values)


def seed_frozen_v1(engine):
    assert inspect(engine).get_table_names() == [], "REFUSED: schema is not empty; nothing was changed"
    sql = Path(__file__).with_name("legacy_v1.sql").read_text()
    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    with engine.begin() as conn:
        for statement in sql.split(";"):
            if statement.strip():
                conn.exec_driver_sql(statement)
        salt = "0123456789abcdef0123456789abcdef"
        old_hash = salt + ":" + hashlib.scrypt(
            PASSWORD.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=5
        ).hex()
        insert(conn, "users", {"id": USER_ID, "username": USERNAME, "password_hash": old_hash})
        insert(conn, "sessions", {
            "token_hash": digest(SESSION), "user_id": USER_ID, "csrf_hash": digest(CSRF),
            "expires_at": 2000000000.0,
        })
        insert(conn, "tasks", {
            "id": TASK_ID, "owner_id": USER_ID, "idempotency_key": digest("frozen-v1-task-key"),
            "request_hash": digest(PROMPT), "prompt": PROMPT, "trace_id": TRACE_ID,
            "status": "failed", "attempt_count": 1, "fence": 1, "attempt_id": ATTEMPT_ID,
            "lease_until": 0.0, "next_attempt_at": 0.0, "result_id": None,
            "error_code": "model_unavailable", "created_at": 1700000000.0,
            "updated_at": 1700000010.0, "model_mode": "deterministic",
        })
        insert(conn, "outbox", {
            "id": EVENT_ID, "task_id": TASK_ID, "event_type": "task.created",
            "payload": '{"fixture":"synthetic-v1-already-sent"}', "sent_at": 1700000001.0,
        })
        insert(conn, "inbox", {"event_id": EVENT_ID, "received_at": 1700000002.0})
        insert(conn, "attempts", {
            "id": ATTEMPT_ID, "task_id": TASK_ID, "fence": 1, "started_at": 1700000003.0,
            "finished_at": 1700000010.0, "outcome": "model_unavailable",
        })
        insert(conn, "task_events", {
            "id": "66666666-6666-4666-8666-666666666666", "task_id": TASK_ID, "trace_id": TRACE_ID,
            "component": "worker", "kind": "failed", "content": "Synthetic retained v1 failure",
            "created_at": 1700000010.0,
        })
        insert(conn, "schema_version", {"version": 1})


def assert_old_schema_readiness_is_503():
    # Start a disposable real HTTP API inside the isolated test container. No
    # production API/Worker exists yet; its stores are the real CI services.
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "18089"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        with httpx.Client(base_url="http://127.0.0.1:18089", timeout=10) as client:
            while time.monotonic() < deadline:
                assert process.poll() is None, "pre-upgrade API exited before readiness evidence"
                try:
                    response = client.get("/readyz")
                except httpx.HTTPError:
                    time.sleep(0.2)
                    continue
                assert response.status_code == 503, "v1 must not appear ready for a v2 runtime"
                body = response.json()
                assert body["mode"] == "production" and body["dependencies"]["mysql"] == "down"
                assert client.get("/healthz").status_code == 200
                return
        raise AssertionError("pre-upgrade API readiness did not respond before deadline")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_frozen_v1_upgrade_repeat_and_future_version_guard():
    from backend.migrate import CURRENT_SCHEMA_VERSION, assert_current_schema, migrate

    engine = engine_for_fixture()
    try:
        seed_frozen_v1(engine)
        before = snapshot(engine)
        definitions = legacy_definitions(engine)
        assert_old_schema_readiness_is_503()
        with pytest.raises(RuntimeError):
            assert_current_schema(engine)
        assert set(inspect(engine).get_table_names()) == {*LEGACY_TABLES, "schema_version"}
        assert snapshot(engine) == before
        assert CURRENT_SCHEMA_VERSION == 2
        # Interrupt after MySQL has really committed the first lab CREATE TABLE,
        # but before its indexes/the remaining table/version marker. This is an
        # injected migration-boundary error, not a claim of process SIGKILL.
        def interrupt_after_committed_ddl(conn, cursor, statement, parameters, context, executemany):
            if statement.strip().replace("`", "").upper().startswith("CREATE TABLE LAB_"):
                raise RuntimeError("synthetic migration interruption after real MySQL DDL")

        event.listen(engine, "after_cursor_execute", interrupt_after_committed_ddl)
        try:
            with pytest.raises(RuntimeError, match="synthetic migration interruption"):
                migrate(engine)
        finally:
            event.remove(engine, "after_cursor_execute", interrupt_after_committed_ddl)
        assert {"lab_records", "lab_kafka_messages"}.intersection(inspect(engine).get_table_names())
        with engine.connect() as conn:
            assert set(conn.execute(text("SELECT version FROM schema_version")).scalars()) == {1}
        assert snapshot(engine) == before
        with pytest.raises(RuntimeError):
            assert_current_schema(engine)
        # Real MySQL reflection must reject a semantically incompatible partial
        # table. This test owns the fresh empty CI schema and this exact index;
        # never remove a user-created constraint or alter a running user's DB.
        partial_tables = set(inspect(engine).get_table_names())
        assert "lab_records" in partial_tables
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE UNIQUE INDEX ci_conflicting_lab_name ON lab_records (name)")
        try:
            with pytest.raises(RuntimeError, match="unique constraints differ"):
                migrate(engine)
            with pytest.raises(RuntimeError):
                assert_current_schema(engine)
            assert set(inspect(engine).get_table_names()) == partial_tables
            assert snapshot(engine) == before
            assert legacy_definitions(engine) == definitions
            with engine.connect() as conn:
                assert set(conn.execute(text("SELECT version FROM schema_version")).scalars()) == {1}
            assert any(
                index["name"] == "ci_conflicting_lab_name" and index["unique"]
                for index in inspect(engine).get_indexes("lab_records")
            ), "refused migration must not silently remove the conflicting constraint"
        finally:
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP INDEX ci_conflicting_lab_name ON lab_records")
        for _ in range(2):
            migrate(engine)
            assert_current_schema(engine)
            with engine.connect() as conn:
                assert set(conn.execute(text("SELECT version FROM schema_version")).scalars()) == {1, 2}
                for table in ("lab_records", "lab_kafka_messages"):
                    assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0
            assert snapshot(engine) == before, "migration changed legacy users/tasks/auth or recovery state"
            assert legacy_definitions(engine) == definitions, "migration changed legacy indexes, constraints or columns"
        # Inject only a synthetic future marker, before API/Worker startup. A
        # failed migration must neither ignore it nor change retained old rows.
        with engine.begin() as conn:
            insert(conn, "schema_version", {"version": 999})
        try:
            with pytest.raises(RuntimeError):
                assert_current_schema(engine)
            with pytest.raises(RuntimeError):
                migrate(engine)
            assert snapshot(engine) == before
            with engine.connect() as conn:
                assert set(conn.execute(text("SELECT version FROM schema_version")).scalars()) == {1, 2, 999}
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM schema_version WHERE version=999"))
        assert_current_schema(engine)
    finally:
        engine.dispose()


def test_upgraded_legacy_password_session_task_and_ownership_after_start():
    engine = engine_for_fixture()
    try:
        before = snapshot(engine)
        assert len(before["users"]) == 1 and before["users"][0]["id"] == USER_ID
        with httpx.Client(base_url=os.environ["TEST_BASE_URL"], timeout=15) as client:
            assert client.get("/readyz").status_code == 200
            client.cookies.set("lab_session", SESSION)
            client.headers["X-CSRF-Token"] = CSRF
            # GET task proves the legacy opaque session still works without
            # calling /auth/me (which intentionally rotates the CSRF token).
            task = client.get(f"/api/v1/tasks/{TASK_ID}")
            assert task.status_code == 200
            assert task.json()["prompt"] == PROMPT and task.json()["status"] == "failed"
            assert client.get(f"/api/v1/tasks/{TASK_ID}/attempts").json()["items"][0]["id"] == ATTEMPT_ID
            assert snapshot(engine) == before, "startup must not rewrite legacy data"
            assert client.post("/api/v1/auth/logout").status_code == 204
            login = client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
            assert login.status_code == 200
            assert login.json()["user"]["id"] == USER_ID
            assert client.get(f"/api/v1/tasks/{TASK_ID}").status_code == 200
        with httpx.Client(base_url=os.environ["TEST_BASE_URL"], timeout=15) as stranger:
            assert stranger.get(f"/api/v1/tasks/{TASK_ID}").status_code == 401
            registered = stranger.post("/api/v1/auth/register", json={
                "username": "ci_v1_upgrade_stranger", "password": "Synthetic-upgrade-stranger!42",
            })
            assert registered.status_code == 201
            assert stranger.get(f"/api/v1/tasks/{TASK_ID}").status_code == 404
            assert stranger.get("/api/v1/tasks").json()["items"] == []
    finally:
        engine.dispose()
