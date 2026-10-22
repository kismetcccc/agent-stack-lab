"""One-shot assertion invoked across host-orchestrated real service outages."""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

BASE = os.getenv("TEST_BASE_URL", "http://api:8000")
STATE = Path("/reports/outage-state.json")


def sql(task_id):
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as conn:
        row = dict(conn.execute(text("SELECT * FROM tasks WHERE id=:id"), {"id": task_id}).mappings().one())
    engine.dispose()
    return row


def main():
    action = sys.argv[1]
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
