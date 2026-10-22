"""One-shot assertion invoked across host-orchestrated real service outages."""

import hashlib
import json
import os
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

BASE = os.getenv("TEST_BASE_URL", "http://api:8000")
STATE = Path("/reports/outage-state.json")
MYSQL_REPORT = Path("/reports/mysql-outage.xml")
MYSQL_PHASES = ("mysql-prepare", "mysql-enqueue", "mysql-unavailable", "mysql-restored", "mysql-complete")
# A stopped container's DNS/SQL failure can take ~20s; do not mistake a client
# timeout for an HTTP 503. Each poll has a separate bounded overall deadline.
MYSQL_HTTP_TIMEOUT = 45
MYSQL_PROMPT = "Explain durable MySQL outage recovery using this synthetic task"


def write_state(state):
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(state, handle)


def checked_json(response, status, label):
    # Never include response.text: an unexpected auth/error response may contain secrets.
    assert response.status_code == status, f"{label}: expected HTTP {status}"
    body = response.json()
    assert isinstance(body, dict), f"{label}: expected JSON object"
    return body


def checked_error(response, status=503, code="database_unavailable"):
    body = checked_json(response, status, "SQL boundary")
    assert set(body) == {"error", "request_id"}, "SQL boundary: invalid error envelope"
    assert set(body["error"]) == {"code", "message"}, "SQL boundary: invalid error fields"
    assert body["error"]["code"] == code, "SQL boundary: wrong error code"
    assert body["request_id"] and body["request_id"] == response.headers.get("X-Request-ID"), (
        "SQL boundary: missing or inconsistent request ID"
    )
    for forbidden in ("Traceback", "sqlalchemy", "pymysql", "DATABASE_URL", "password_hash", "token_hash"):
        assert forbidden not in response.text, "SQL boundary: unsafe error detail"


def wait_mysql_readiness(client, *, up, timeout=180):
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            response = client.get("/readyz", timeout=min(MYSQL_HTTP_TIMEOUT, remaining))
        except httpx.HTTPError:
            pass  # A transport error is NOT evidence of the required HTTP response.
        else:
            assert response.status_code in (200, 503), "readiness returned unexpected HTTP status"
            body = response.json()
            assert body["mode"] == "production", "probe requires real adapters"
            assert body["model_mode"] == "deterministic", "probe forbids live model mode"
            expected = {"mysql": "up" if up else "down", "mongo": "up", "kafka": "up"}
            if body["dependencies"] == expected and response.status_code == (200 if up else 503):
                assert body["status"] == ("ready" if up else "not_ready")
                return
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise AssertionError("MySQL readiness deadline exceeded; required HTTP state not observed")


def mysql_rows(query, **params):
    url = os.environ["DATABASE_URL"]
    assert url.startswith("mysql+pymysql://"), "MySQL probe requires the real PyMySQL adapter"
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5},
    )
    try:
        with engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params).mappings()]
    finally:
        engine.dispose()


def mysql_task(task_id):
    rows = mysql_rows("SELECT id,owner_id,status,attempt_count,result_id FROM tasks WHERE id=:id", id=task_id)
    assert len(rows) == 1, "expected one persisted task"
    return rows[0]


def registered_session(client):
    body = checked_json(
        client.post(
            "/api/v1/auth/register",
            json={
                "username": "sql_outage_" + uuid.uuid4().hex[:16],
                "password": "Synthetic-only!" + uuid.uuid4().hex,
            },
        ),
        201,
        "register synthetic account",
    )
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return {"cookies": dict(client.cookies), "csrf": body["csrf_token"], "owner_id": body["user"]["id"]}


def mysql_client(session=None):
    session = session or {}
    return httpx.Client(
        base_url=BASE,
        timeout=MYSQL_HTTP_TIMEOUT,
        cookies=session.get("cookies", {}),
        headers={"X-CSRF-Token": session.get("csrf", "")},
    )


def mysql_submit(client, key):
    return client.post("/api/v1/tasks", json={"prompt": MYSQL_PROMPT}, headers={"Idempotency-Key": key})


def completed_result(client, task_id, timeout=180):
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        task = checked_json(
            client.get(f"/api/v1/tasks/{task_id}", timeout=min(MYSQL_HTTP_TIMEOUT, remaining)),
            200,
            "recover persisted task",
        )
        assert task["status"] != "failed", "persisted task failed instead of recovering"
        if task["status"] == "succeeded":
            result = checked_json(client.get(f"/api/v1/tasks/{task_id}/results"), 200, "committed result")
            assert result["task_id"] == task_id
            assert result["model_mode"] == "deterministic" and result["controller_mode"] == "scripted_test"
            steps = checked_json(client.get(f"/api/v1/tasks/{task_id}/agent-steps"), 200, "committed steps")
            assert steps["availability"] == "committed" and steps["items"][-1]["kind"] == "final"
            return result
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise AssertionError("persisted task recovery deadline exceeded")


def result_digest(result):
    payload = {key: value for key, value in result.items() if key != "cache_status"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def assert_warm_cache(result_id):
    from redis import Redis

    with Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3) as cache:
        assert cache.exists("result:" + result_id), (
            "cached result must exist during SQL authorization failure"
        )


def assert_pending(state):
    task = mysql_task(state["pending_id"])
    assert task["status"] == "pending" and task["result_id"] is None and task["attempt_count"] == 0, (
        "stopped Worker must leave durable work pending, not successful"
    )
    rows = mysql_rows(
        "SELECT id,sent_at FROM outbox WHERE task_id=:id AND event_type='task.created'", id=task["id"]
    )
    assert len(rows) == 1 and rows[0]["sent_at"] is None, "pending task must retain one unsent outbox"
    if "pending_outbox_id" in state:
        assert rows[0]["id"] == state["pending_outbox_id"], "restart must preserve the original outbox"
    assert task["owner_id"] == state["owner"]["owner_id"], "restart must preserve ownership"
    return rows[0]["id"]


def assert_owner_boundaries(client, stranger, task_ids):
    for task_id in task_ids:
        for suffix in ("", "/events", "/attempts", "/results", "/agent-steps"):
            checked_error(stranger.get(f"/api/v1/tasks/{task_id}{suffix}"), 404, "not_found")
        assert checked_json(client.get(f"/api/v1/tasks/{task_id}"), 200, "owner access")["id"] == task_id
    listing = checked_json(stranger.get("/api/v1/tasks"), 200, "stranger task listing")
    assert listing["items"] == [] and listing["total"] == 0, "owner boundary leaked tasks into listing"


def write_mysql_report(phases, error_type=None):
    complete = tuple(phases) == MYSQL_PHASES
    suite = ET.Element(
        "testsuite",
        name="real-compose-mysql-outage-probe",
        tests="1",
        failures="1" if error_type else "0",
        errors="0",
        skipped="0" if complete or error_type else "1",
    )
    properties = ET.SubElement(suite, "properties")
    for name, value in (
        ("evidence_kind", "host-orchestrated real Compose probe; NOT a pytest test"),
        ("model_mode", "deterministic"),
        ("completed_phases", str(len(phases))),
    ):
        ET.SubElement(properties, "property", name=name, value=value)
    case = ET.SubElement(suite, "testcase", classname="real_compose_probe", name="mysql_outage_recovery")
    if error_type:
        ET.SubElement(
            case, "failure", type=error_type, message="MySQL probe failed; no secret details recorded"
        )
    elif not complete:
        ET.SubElement(case, "skipped", message="MySQL scenario incomplete; recovery not yet verified")
    ET.SubElement(case, "system-out").text = "\n".join("PASS: " + phase for phase in phases)
    MYSQL_REPORT.write_text(ET.tostring(suite, encoding="unicode"))


def mysql_phase(action, state):
    if action == "mysql-prepare":
        with mysql_client() as owner, mysql_client() as stranger:
            wait_mysql_readiness(owner, up=True)
            state.update(owner=registered_session(owner), stranger=registered_session(stranger))
            task = checked_json(mysql_submit(owner, uuid.uuid4().hex), 202, "submit baseline task")
            result = completed_result(owner, task["id"])
            warm = checked_json(owner.get(f"/api/v1/tasks/{task['id']}/results"), 200, "warm result cache")
            assert warm["cache_status"] == "hit", "baseline must prove a real Redis cache hit"
            state.update(
                committed=mysql_task(task["id"]),
                result_digest=result_digest(result),
                pending_key=uuid.uuid4().hex,
                blocked_key=uuid.uuid4().hex,
            )
            assert state["committed"]["result_id"], "baseline needs committed SQL result reference"
            assert_owner_boundaries(owner, stranger, [task["id"]])
        return
    with mysql_client(state["owner"]) as owner, mysql_client(state["stranger"]) as stranger:
        committed = state["committed"]
        if action == "mysql-enqueue":
            task = checked_json(mysql_submit(owner, state["pending_key"]), 202, "enqueue before SQL outage")
            state["pending_id"] = task["id"]
            state["pending_outbox_id"] = assert_pending(state)
        elif action == "mysql-unavailable":
            wait_mysql_readiness(owner, up=False, timeout=120)
            checked_json(owner.get("/healthz"), 200, "liveness during SQL outage")
            # Prove Redis is warm both before and after HTTP requests: a cache miss
            # must not accidentally make the authorization regression test pass.
            assert_warm_cache(committed["result_id"])
            for client in (owner, stranger):
                checked_error(client.get(f"/api/v1/tasks/{committed['id']}/results"))
            assert_warm_cache(committed["result_id"])
            checked_error(mysql_submit(owner, state["blocked_key"]))
            for path in (
                "/api/v1/tasks",
                f"/api/v1/tasks/{state['pending_id']}",
                f"/api/v1/tasks/{committed['id']}/agent-steps",
            ):
                checked_error(owner.get(path))
        elif action == "mysql-restored":
            wait_mysql_readiness(owner, up=True)
            assert_pending(state)  # Host must not restart Worker until SQL is ready and this is checked.
            assert mysql_task(committed["id"]) == committed, "restart changed the committed task"
            assert result_digest(completed_result(owner, committed["id"])) == state["result_digest"], (
                "restart changed the persisted result"
            )
            absent = mysql_rows(
                "SELECT id FROM tasks WHERE owner_id=:owner AND idempotency_key=:key",
                owner=state["owner"]["owner_id"],
                key=hashlib.sha256(state["blocked_key"].encode()).hexdigest(),
            )
            assert not absent, "HTTP 503 create must not leave an accepted task"
            replay = checked_json(mysql_submit(owner, state["pending_key"]), 202, "durable idempotent replay")
            assert replay["id"] == state["pending_id"], "restart lost idempotency"
            assert_owner_boundaries(owner, stranger, [committed["id"], state["pending_id"]])
        elif action == "mysql-complete":
            completed_result(owner, state["pending_id"])
            pending = mysql_task(state["pending_id"])
            assert pending["status"] == "succeeded" and pending["result_id"] and pending["attempt_count"] >= 1
            delivery = mysql_rows(
                "SELECT o.sent_at,i.event_id FROM outbox o LEFT JOIN inbox i ON i.event_id=o.id WHERE o.id=:id",
                id=state["pending_outbox_id"],
            )
            assert len(delivery) == 1 and delivery[0]["sent_at"] is not None and delivery[0]["event_id"], (
                "original outbox must be delivered and persisted in inbox after recovery"
            )
            assert mysql_task(committed["id"]) == committed, "Worker restart re-executed the baseline task"
            assert_owner_boundaries(owner, stranger, [committed["id"], pending["id"]])
            wait_mysql_readiness(owner, up=True)


def run_mysql_phase(action):
    phases = []
    try:
        assert action in MYSQL_PHASES, "unknown MySQL probe phase"
        if action == "mysql-prepare":
            state = {"scenario": "mysql-outage", "phases": []}
            write_mysql_report([])
        else:
            state = json.loads(STATE.read_text())
        assert state["scenario"] == "mysql-outage", "unexpected outage state"
        phases = state["phases"]
        assert phases == list(MYSQL_PHASES[: MYSQL_PHASES.index(action)]), "MySQL phases must run in order"
        mysql_phase(action, state)
        phases.append(action)
        write_state(state)
        write_mysql_report(phases)
        print(f"PASS: real Compose MySQL probe phase {len(phases)}/{len(MYSQL_PHASES)}: {action}")
        if action == "mysql-complete":
            STATE.unlink()
            print("PASS: 1 real MySQL outage/recovery scenario; 5 phases; not additional pytest tests")
    except Exception as exc:
        # Deliberately suppress raw HTTP/driver exceptions, URLs, cookies and tracebacks.
        write_mysql_report(phases, type(exc).__name__)
        failed_phase = action if action in MYSQL_PHASES else "unknown phase"
        print(
            f"FAIL: MySQL outage probe {failed_phase} ({type(exc).__name__}); see sanitized phase report",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def sql(task_id):
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as conn:
        row = dict(conn.execute(text("SELECT * FROM tasks WHERE id=:id"), {"id": task_id}).mappings().one())
    engine.dispose()
    return row


def main():
    action = sys.argv[1]
    if action.startswith("mysql-"):
        run_mysql_phase(action)
        return
    if action == "submit":
        with httpx.Client(base_url=BASE, timeout=20) as client:
            r = client.post(
                "/api/v1/auth/register",
                json={"username": "outage_" + uuid.uuid4().hex[:16], "password": "Test-only!42-password"},
            )
            assert r.status_code in (200, 201), r.text
            csrf = r.json()["csrf_token"]
            client.headers["X-CSRF-Token"] = csrf
            r = client.post(
                "/api/v1/tasks",
                json={"prompt": "Demonstrate durable outage recovery"},
                headers={"Idempotency-Key": uuid.uuid4().hex},
            )
            assert r.status_code == 202, r.text
            STATE.write_text(
                json.dumps({"task_id": r.json()["id"], "cookies": dict(client.cookies), "csrf": csrf})
            )
            os.chmod(STATE, 0o600)
            print("accepted task during outage")
        return
    state = json.loads(STATE.read_text())
    task_id = state["task_id"]
    if action == "hook-evidence":
        point = os.environ["TEST_HOOK_POINT"]
        task = sql(task_id)
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            outbox = (
                conn.execute(
                    text("SELECT id,sent_at FROM outbox WHERE task_id=:id AND event_type='task.created'"),
                    {"id": task_id},
                )
                .mappings()
                .one()
            )
            if point == "after_outbox_publish":
                assert outbox["sent_at"] is None and task["status"] == "pending"
            elif point == "after_inbox_commit":
                assert (
                    conn.execute(
                        text("SELECT COUNT(*) FROM inbox WHERE event_id=:id"), {"id": outbox["id"]}
                    ).scalar()
                    == 1
                )
            else:
                assert task["status"] == "running" and task["result_id"] is None
                if point == "after_mongo_save":
                    from pymongo import MongoClient

                    mongo = MongoClient(os.environ["MONGO_URL"])
                    assert mongo.agent_lab.results.find_one({"_id": task_id + ":" + task["attempt_id"]})
                    mongo.close()
        engine.dispose()
        print("verified durable evidence at crash boundary:", point)
    elif action == "pending":
        time.sleep(5)
        task = sql(task_id)
        assert task["status"] == "pending" and task["result_id"] is None, task
        print("SQL pending, no false success")
    elif action == "no-success":
        time.sleep(5)
        task = sql(task_id)
        assert task["status"] != "succeeded" and task["result_id"] is None, task
        print("Mongo outage did not create false success")
    elif action == "read-unavailable":
        with httpx.Client(base_url=BASE, cookies=state["cookies"], timeout=15) as client:
            r = client.get(f"/api/v1/tasks/{task_id}/results")
            assert r.status_code == 503 and r.json()["error"]["code"] == "document_unavailable", r.text
            actions = client.get(f"/api/v1/tasks/{task_id}/agent-steps")
            assert actions.status_code == 503, actions.text
            assert actions.json()["error"]["code"] == "document_unavailable"
            assert client.get("/healthz").status_code == 200
            assert client.get("/readyz").status_code == 503
            assert sql(task_id)["status"] == "succeeded"
            print("Mongo read failure is 503; committed SQL state stays authoritative; liveness unaffected")
    elif action in ("complete", "complete-retain"):
        with httpx.Client(base_url=BASE, cookies=state["cookies"], timeout=15) as client:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                r = client.get(f"/api/v1/tasks/{task_id}")
                assert r.status_code == 200, r.text
                task = r.json()
                assert task["status"] != "failed", task
                if task["status"] == "succeeded":
                    assert sql(task_id)["result_id"]
                    result = client.get(f"/api/v1/tasks/{task_id}/results")
                    if result.status_code == 503:
                        time.sleep(1)
                        continue
                    assert result.status_code == 200
                    actions = client.get(f"/api/v1/tasks/{task_id}/agent-steps")
                    assert actions.status_code == 200, actions.text
                    assert actions.json()["availability"] == "committed"
                    assert actions.json()["controller_mode"] == "scripted_test"
                    assert actions.json()["items"][-1]["kind"] == "final"
                    if os.getenv("EXPECT_REDIS_DOWN") == "1":
                        assert result.json()["cache_status"] == "unavailable"
                    if action == "complete-retain":
                        from redis import Redis

                        redis = Redis.from_url(os.environ["REDIS_URL"])
                        redis.delete("result:" + sql(task_id)["result_id"])
                        redis.close()
                    else:
                        STATE.unlink()
                    print("recovered task has committed SQL result reference and readable Mongo result")
                    return
                time.sleep(1)
        raise AssertionError("recovery timed out")
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main()
