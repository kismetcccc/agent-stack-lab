"""Private-state, sanitized evidence for host-orchestrated REAL Docker SIGKILL windows.

This is not a pytest test and never changes leases, offsets, or production time.
Only synthetic deterministic tasks are submitted. The host owns Docker lifecycle.
"""

import json
import logging
import os
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import text

from backend.config import Settings
from backend.db import connect
from backend.faults import PAUSE_SECONDS, valid_id

POINTS = ("after_outbox_publish", "after_inbox_commit", "after_claim", "after_mongo_save")
PHASES = ("prepared", "boundary_verified", "sigkill_verified", "recovered")
REPORTS = Path("/reports")
STATE = REPORTS / "crash-state.json"  # Private cookies/CSRF; NEVER upload this file.
GROUP = "agent-executors-v1"


def private_write(state):
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(state, handle)


def report(state):
    """Allowlist only: never serialize private state, exception messages or responses."""
    cases = []
    for point in POINTS:
        case = state["cases"][point]
        phases = [phase for phase in PHASES if phase in case["phases"]]
        status = (
            "failed"
            if case.get("failed") or phases != case["phases"]
            else ("passed" if case["phases"] == list(PHASES) else "incomplete")
        )
        cases.append({"window": point, "status": status, "completed_phases": phases})
    complete = all(case["status"] == "passed" for case in cases)
    outcome = (
        "failed"
        if state.get("failed") or any(case["status"] == "failed" for case in cases)
        else ("passed" if complete and state.get("cleanup_verified") else "incomplete")
    )
    summary = {
        "evidence_kind": "real-compose-sigkill-probe-not-pytest",
        "model_mode": "deterministic",
        "status": outcome,
        "cleanup_verified": bool(state.get("cleanup_verified")),
        "windows": cases,
    }
    (REPORTS / "crash-windows.json").write_text(json.dumps(summary, indent=2) + "\n")
    suite = ET.Element(
        "testsuite",
        name="real-compose-crash-windows",
        tests="4",
        failures=str(sum(case["status"] == "failed" for case in cases)),
        errors="0",
        skipped=str(sum(case["status"] == "incomplete" for case in cases)),
    )
    props = ET.SubElement(suite, "properties")
    for key in ("evidence_kind", "model_mode", "status", "cleanup_verified"):
        ET.SubElement(props, "property", name=key, value=str(summary[key]))
    for case in cases:
        item = ET.SubElement(suite, "testcase", classname="real_compose_sigkill", name=case["window"])
        if case["status"] == "failed":
            ET.SubElement(item, "failure", message="Crash window or restoration failed; details suppressed")
        elif case["status"] == "incomplete":
            ET.SubElement(item, "skipped", message="Actual SIGKILL/recovery evidence incomplete; NOT PASS")
        ET.SubElement(item, "system-out").text = "\n".join(case["completed_phases"])
    (REPORTS / "crash-windows.xml").write_text(ET.tostring(suite, encoding="unicode"))


def checked(response, status):
    assert response.status_code == status, "unexpected HTTP status; response suppressed"
    body = response.json()
    assert isinstance(body, dict), "unexpected HTTP schema"
    return body


def client(state=None):
    session = (state or {}).get("session", {})
    return httpx.Client(
        base_url=os.getenv("TEST_BASE_URL", "http://api:8000"),
        timeout=10,
        cookies=session.get("cookies", {}),
        headers={"X-CSRF-Token": session.get("csrf", "")},
    )


def rows(query, **params):
    settings = Settings()
    assert settings.mode == "production" and settings.model_mode == "deterministic"
    assert settings.database_url.startswith("mysql+pymysql://")
    engine, _ = connect(settings.database_url)
    try:
        with engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params).mappings()]
    finally:
        engine.dispose()


def task_row(task_id):
    return rows(
        "SELECT id,status,attempt_count,attempt_id,fence,lease_until,result_id FROM tasks WHERE id=:id",
        id=task_id,
    )[0]


def outbox_row(task_id):
    found = rows(
        "SELECT id,sent_at,payload FROM outbox WHERE task_id=:id AND event_type='task.created'", id=task_id
    )
    assert len(found) == 1, "task must have exactly one creation outbox"
    return found[0]


def observer():
    from confluent_kafka import Consumer

    # Never subscribe/join the Worker group, reset offsets or commit from this read-only observer.
    return Consumer(
        {
            "bootstrap.servers": Settings().kafka_servers,
            "group.id": GROUP,
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "logger": logging.getLogger("quiet_kafka"),
        }
    )


def positions():
    from confluent_kafka import TopicPartition

    consumer = observer()
    try:
        topic = Settings().topic
        metadata = consumer.list_topics(topic, timeout=10).topics[topic]
        assert not metadata.error
        return {
            str(partition): consumer.get_watermark_offsets(
                TopicPartition(topic, partition), timeout=10, cached=False
            )[1]
            for partition in metadata.partitions
        }
    finally:
        consumer.close()


def committed(partition):
    from confluent_kafka import TopicPartition

    consumer = observer()
    try:
        result = consumer.committed([TopicPartition(Settings().topic, partition)], timeout=10)[0]
        assert not result.error
        return result.offset  # Negative means no offset committed yet, also before the target.
    finally:
        consumer.close()


def target_records(case):
    """Scan only the finite interval since this synthetic task was created; no offset writes."""
    from confluent_kafka import TopicPartition

    consumer = observer()
    records = []
    try:
        ends = positions()
        for partition, start in case["start_offsets"].items():
            end = ends[partition]
            if start == end:
                continue
            consumer.assign([TopicPartition(Settings().topic, int(partition), start)])
            deadline = time.monotonic() + 15
            position = start
            while position < end:
                assert time.monotonic() < deadline, "bounded Kafka scan deadline exceeded"
                msg = consumer.poll(0.5)
                if not msg:
                    continue
                assert not msg.error(), "Kafka observer failed"
                position = msg.offset() + 1
                event = json.loads(msg.value())
                if event.get("task_id") == case["task_id"]:
                    assert event["event_id"] == case["event"]["event_id"], "replay changed stable event ID"
                    records.append({"partition": msg.partition(), "offset": msg.offset()})
        return records
    finally:
        consumer.close()


def mongo_document(result_id):
    from pymongo import MongoClient

    with MongoClient(Settings().mongo_url, serverSelectionTimeoutMS=3000, timeoutMS=5000) as mongo:
        return mongo.agent_lab.results.find_one({"_id": result_id}, {"task_id": 1, "attempt_id": 1})


def prepare(state, point):
    case = state["cases"][point]
    assert not case["phases"], "window cannot be rerun against old evidence"
    case.update(run_id=str(uuid.uuid4()), start_offsets=positions())
    with client() as http:
        ready = checked(http.get("/readyz"), 200)
        assert ready["mode"] == "production" and ready["model_mode"] == "deterministic"
        auth = checked(
            http.post(
                "/api/v1/auth/register",
                json={
                    "username": "crash_" + uuid.uuid4().hex[:20],
                    "password": "Synthetic-only!" + uuid.uuid4().hex,
                },
            ),
            201,
        )
        case["session"] = {"cookies": dict(http.cookies), "csrf": auth["csrf_token"]}
        http.headers["X-CSRF-Token"] = auth["csrf_token"]
        task = checked(
            http.post(
                "/api/v1/tasks",
                json={"prompt": "Synthetic durable crash boundary task"},
                headers={"Idempotency-Key": uuid.uuid4().hex},
            ),
            202,
        )
        case["task_id"] = task["id"]
    task = task_row(case["task_id"])
    assert task["status"] == "pending" and task["attempt_count"] == 0 and task["result_id"] is None
    outbox = outbox_row(task["id"])
    assert outbox["sent_at"] is None, "host must stop Worker before submitting"
    case["event"] = json.loads(outbox["payload"])


def boundary(case, point):
    marker = json.loads(os.environ["TEST_HOOK_MARKER"])
    assert marker["version"] == 1 and marker["point"] == point
    assert marker["task_id"] == case["task_id"] and marker["run_id"] == case["run_id"]
    assert marker["created_at"] <= time.time() < marker["expires_at"]
    assert marker["expires_at"] - marker["created_at"] == PAUSE_SECONDS
    case["marker"] = marker  # Host separately validates /proc identity inside the Worker container.
    durable_boundary(case, point)


def durable_boundary(case, point):
    """Check before AND after actual SIGKILL; never accept just a transient marker or exit code."""
    marker = case["marker"]
    task = task_row(case["task_id"])
    outbox = outbox_row(task["id"])
    assert outbox["id"] == case["event"]["event_id"]
    if point == "after_outbox_publish":
        # Only relay is paused. Independent consumer/executor may already be ready/running/succeeded;
        # requiring pending here would reject a correct concurrent execution, not strengthen safety.
        assert marker["event_id"] == outbox["id"] and outbox["sent_at"] is None
        assert target_records(case), "Kafka must contain the acknowledged target event"
    elif point == "after_inbox_commit":
        assert marker["event_id"] == outbox["id"] and marker["topic"] == Settings().topic
        assert len(rows("SELECT event_id FROM inbox WHERE event_id=:id", id=outbox["id"])) == 1
        assert committed(marker["partition"]) <= marker["offset"], "target offset was already committed"
        assert {"partition": marker["partition"], "offset": marker["offset"]} in target_records(case)
    else:
        assert task["status"] == "running" and task["result_id"] is None
        assert task["attempt_id"] == marker["attempt_id"] and task["fence"] == marker["fence"]
        attempts = rows("SELECT id,fence,outcome FROM attempts WHERE task_id=:id", id=task["id"])
        assert attempts == [{"id": marker["attempt_id"], "fence": marker["fence"], "outcome": "running"}]
        orphan = mongo_document(task["id"] + ":" + marker["attempt_id"])
        if point == "after_mongo_save":
            assert orphan and orphan["task_id"] == task["id"] and orphan["attempt_id"] == marker["attempt_id"]
        else:
            assert orphan is None, "claim boundary precedes document persistence"
        with client(case) as http:
            checked(http.get(f"/api/v1/tasks/{task['id']}/results"), 409)
            steps = checked(http.get(f"/api/v1/tasks/{task['id']}/agent-steps"), 200)
            assert steps["availability"] == "not_committed" and steps["items"] == []


def eventually(check, seconds=150):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise AssertionError("bounded recovery deadline exceeded")


def duplicate_position(event):
    from confluent_kafka import Producer

    produced = []
    producer = Producer(
        {
            "bootstrap.servers": Settings().kafka_servers,
            "enable.idempotence": True,
            "delivery.timeout.ms": 10000,
            "logger": logging.getLogger("quiet_kafka"),
        }
    )
    producer.produce(
        Settings().topic,
        key=event["task_id"],
        value=json.dumps(event),
        callback=lambda error, msg: produced.append((error, msg.partition(), msg.offset())),
    )
    assert producer.flush(12) == 0 and len(produced) == 1 and not produced[0][0]
    return produced[0][1:]


def committed_api(case, task):
    with client(case) as http:
        result = checked(http.get(f"/api/v1/tasks/{task['id']}/results"), 200)
        # Public ResultResponse deliberately omits attempt_id: use SQL/Mongo and agent-steps linkage.
        assert result["task_id"] == task["id"]
        assert result["model_mode"] == "deterministic" and result["controller_mode"] == "scripted_test"
        steps = checked(http.get(f"/api/v1/tasks/{task['id']}/agent-steps"), 200)
        assert steps["availability"] == "committed" and steps["items"][-1]["kind"] == "final"
        assert {item["attempt_id"] for item in steps["items"]} == {task["attempt_id"]}


def recovered(case, point):
    def succeeded():
        task = task_row(case["task_id"])
        assert task["status"] != "failed", "crash recovery reached a failed terminal state"
        return task["status"] == "succeeded"

    eventually(succeeded)
    # Task success can precede relay's sent_at update; wait for the independently owned boundary.
    eventually(lambda: outbox_row(case["task_id"])["sent_at"] is not None, seconds=45)
    task = task_row(case["task_id"])
    assert task["result_id"] == task["id"] + ":" + task["attempt_id"]
    doc = mongo_document(task["result_id"])
    assert doc and doc["attempt_id"] == task["attempt_id"]
    outbox = outbox_row(task["id"])
    assert outbox["id"] == case["event"]["event_id"] and outbox["sent_at"] is not None
    assert len(rows("SELECT event_id FROM inbox WHERE event_id=:id", id=outbox["id"])) == 1
    if point == "after_outbox_publish":
        # Before adding our explicit duplicate, prove relay itself replayed the same event after SIGKILL.
        assert len(target_records(case)) >= 2, "unsent outbox was not replayed after restart"
    elif point == "after_inbox_commit":
        marker = case["marker"]
        eventually(lambda: committed(marker["partition"]) > marker["offset"], seconds=45)
    else:
        marker = case["marker"]
        assert task["attempt_count"] == 2 and task["fence"] > marker["fence"]
        assert task["attempt_id"] != marker["attempt_id"]
        old = rows("SELECT outcome FROM attempts WHERE id=:id", id=marker["attempt_id"])
        assert old == [{"outcome": "lease_expired"}], "old attempt must recover through real lease expiration"
        stale_id = task["id"] + ":" + marker["attempt_id"]
        if point == "after_mongo_save":
            assert mongo_document(stale_id) and stale_id != task["result_id"]
        from backend.runtime import Runtime

        runtime = Runtime()
        try:
            # Prove post-commit isolation, NOT the fence predicate alone (terminal status also guards).
            # The separate recovery pytest covers stale finalize while a newer attempt is running.
            stale = SimpleNamespace(id=task["id"], attempt_id=marker["attempt_id"], fence=marker["fence"])
            assert runtime.tasks.finalize(stale, stale_id) is False
        finally:
            runtime.documents.client.close()
            runtime.engine.dispose()
        assert task_row(task["id"]) == task, "stale attempt changed committed SQL state"
    committed_api(case, task)
    # Prove the running hook-free consumer processes another duplicate without new work/result/fence.
    partition, offset = duplicate_position(case["event"])
    eventually(lambda: committed(partition) > offset, seconds=45)
    assert task_row(task["id"]) == task, "duplicate event re-executed or changed the completed task"
    assert len(rows("SELECT event_id FROM inbox WHERE event_id=:id", id=outbox["id"])) == 1
    assert len(rows("SELECT id FROM attempts WHERE task_id=:id", id=task["id"])) == task["attempt_count"]
    with client(case) as http:
        assert http.post("/api/v1/auth/logout").status_code == 204
    case.pop("session", None)


def main():
    logging.getLogger("quiet_kafka").addHandler(logging.NullHandler())
    logging.getLogger("quiet_kafka").propagate = False
    action = sys.argv[1]
    point = os.getenv("TEST_HOOK_POINT")
    state = None
    try:
        if action == "init":
            assert not STATE.exists(), "stale private state requires cleanup, never overwrite an earlier run"
            state = {"cases": {name: {"phases": []} for name in POINTS}}
        else:
            state = json.loads(STATE.read_text())
        if action == "identity":
            case = state["cases"][point]
            assert valid_id(case["task_id"]) and valid_id(case["run_id"])
            print(case["task_id"], case["run_id"])
            return
        if action == "cleanup":
            state["cleanup_verified"] = os.getenv("TEST_CLEANUP_OK") == "1"
            if not state["cleanup_verified"] or os.getenv("TEST_RUN_FAILED") == "1":
                state["failed"] = True
                if point in POINTS:
                    state["cases"][point]["failed"] = True
            report(state)
            STATE.unlink()  # Credentials are removed on both success and failure.
            return
        if action != "init":
            assert point in POINTS
            case = state["cases"][point]
            phase = {
                "prepare": "prepared",
                "boundary": "boundary_verified",
                "killed": "sigkill_verified",
                "recover": "recovered",
            }[action]
            assert case["phases"] == list(PHASES[: PHASES.index(phase)]), "phases must run in order"
            if action == "prepare":
                prepare(state, point)
            elif action == "boundary":
                boundary(case, point)
            elif action == "killed":
                assert os.getenv("TEST_KILL_VERIFIED") == "1", "host must verify actual SIGKILL exit 137"
                assert time.time() < case["marker"]["expires_at"], "kill evidence exceeded hook lifetime"
                durable_boundary(case, point)  # Worker remains stopped; no /proc liveness check here.
            elif action == "recover":
                recovered(case, point)
            case["phases"].append(phase)
        private_write(state)
        report(state)
        if action != "init":
            print(f"VERIFIED: real Compose crash window {point}: {action}")
    except Exception:
        try:
            if state is not None:
                state["failed"] = True
                if point in POINTS:
                    state["cases"][point]["failed"] = True
                private_write(state)
                report(state)
        except Exception:
            print("FAIL: sanitized evidence could not be saved; run is NOT PASS", file=sys.stderr)
        print("FAIL: crash probe assertion/dependency error; sensitive details suppressed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
