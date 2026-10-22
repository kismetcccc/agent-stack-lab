"""Real-store acceptance for the scripted Agent; never a real-LLM claim."""

import json
import os
import time
import uuid
from decimal import Decimal

import httpx
import pytest
from confluent_kafka import Producer
from conftest import completed, envelope, eventually, rows, submit
from sqlalchemy import text

pytestmark = pytest.mark.integration
DEMO = "目标：[search:销量] [stats]\n材料：销量 10 20 30"


def test_scripted_agent_durable_actions_cache_and_redelivery(user, stores, base_url):
    task_id = submit(user, DEMO)["id"]
    completed(user, task_id)
    sql_task = rows(stores, "SELECT * FROM tasks WHERE id=:id", id=task_id)[0]
    result_id = sql_task["result_id"]
    document = stores["mongo"].agent_lab.results.find_one({"_id": result_id})
    assert document is not None
    assert document["execution_kind"] == "single_agent"
    assert document["controller_mode"] == "scripted_test"
    assert sql_task["attempt_count"] == 1
    path = f"/api/v1/tasks/{task_id}/agent-steps"
    stores["redis"].delete("result:" + result_id)
    response = user.get(path)
    assert response.status_code == 200
    actions = response.json()
    assert actions["availability"] == "committed"
    assert actions["execution_kind"] == "single_agent"
    assert actions["controller_mode"] == "scripted_test"
    steps = actions["items"]
    assert steps == document["steps"]
    assert [s["kind"] for s in steps] == ["tool_call", "tool_result"] * 3 + ["final"]
    calls = [s for s in steps if s["kind"] == "tool_call"]
    observations = [s for s in steps if s["kind"] == "tool_result"]
    assert [s["tool_name"] for s in calls] == ["read_text", "search_text", "numeric_stats"]
    assert [s["tool_name"] for s in observations] == [s["tool_name"] for s in calls]
    assert calls[1]["arguments"]["query"] == "销量"
    stats = observations[2]["result"]
    assert stats["count"] == 3
    for key, expected in {"sum": 60, "mean": 20, "min": 10, "max": 30}.items():
        assert Decimal(str(stats[key])) == expected
    assert len({s["id"] for s in steps}) == len(steps)
    assert [s["sequence"] for s in steps] == list(range(1, len(steps) + 1))
    for step in steps:
        assert step["task_id"] == task_id and step["attempt_id"] == sql_task["attempt_id"]
        assert step["execution_kind"] == "single_agent" and step["controller_mode"] == "scripted_test"
        assert step["created_at"] and step["content"]
        assert not {"thought", "reasoning", "scratchpad", "messages"}.intersection(step)
    lifecycle = user.get(f"/api/v1/tasks/{task_id}/events").json()["items"]
    assert {"pending", "outbox_sent", "ready", "running", "succeeded"} <= {s["kind"] for s in lifecycle}
    assert not {"tool_call", "tool_result", "final"}.intersection(s["kind"] for s in lifecycle)
    # Refresh re-reads the same immutable committed attempt through the real cache.
    assert user.get(path).json() == actions
    report = user.get(f"/api/v1/tasks/{task_id}/results").json()
    assert report["cache_status"] == "hit"
    assert report["execution_kind"] == "single_agent" and report["controller_mode"] == "scripted_test"
    assert 0 < stores["redis"].ttl("result:" + result_id) <= 300
    with httpx.Client(base_url=base_url) as stranger:
        assert stranger.get(path).status_code == 401
        registered = stranger.post(
            "/api/v1/auth/register",
            json={"username": "agent_other_" + uuid.uuid4().hex[:16], "password": "Agent-other!password42"},
        )
        assert registered.status_code in (200, 201)
        assert stranger.get(path).status_code == 404
    # Republish actual outbox payload, not a synthesized in-memory bus message.
    event = envelope(stores, task_id)
    producer = Producer({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"]})
    delivery = []
    producer.produce(
        os.getenv("KAFKA_TOPIC", "agent.tasks"),
        key=task_id,
        value=json.dumps(event),
        on_delivery=lambda err, msg: delivery.append(err),
    )
    assert producer.flush(15) == 0 and delivery == [None]
    time.sleep(4)
    assert len(rows(stores, "SELECT * FROM attempts WHERE task_id=:id", id=task_id)) == 1
    assert len(rows(stores, "SELECT * FROM inbox WHERE event_id=:id", id=event["event_id"])) == 1
    assert user.get(path).json() == actions
    assert stores["mongo"].agent_lab.results.count_documents({"task_id": task_id}) == 1


@pytest.mark.parametrize(
    "mode,controller", [("deterministic", "legacy_deterministic_echo"), ("live", "legacy_live_single_call")]
)
def test_legacy_document_read_is_truthful_and_never_rewritten(user, stores, mode, controller):
    task_id = submit(user, "Legacy compatibility fixture")["id"]
    completed(user, task_id)
    task = rows(stores, "SELECT * FROM tasks WHERE id=:id", id=task_id)[0]
    # Explicit isolated historical-data fixture: no live provider is invoked.
    legacy_id = "legacy-" + str(uuid.uuid4())
    legacy = {
        "_id": legacy_id,
        "task_id": task_id,
        "attempt_id": task["attempt_id"],
        "model_mode": mode,
        "content": "Historical single-call content",
        "steps": [{"id": "old-summary", "kind": "summary", "content": "Historical summary"}],
    }
    collection = stores["mongo"].agent_lab.results
    collection.insert_one(legacy)
    with stores["sql"].begin() as conn:
        conn.execute(
            text("UPDATE tasks SET result_id=:result, model_mode=:mode WHERE id=:id"),
            {"result": legacy_id, "mode": mode, "id": task_id},
        )
    stores["redis"].delete("result:" + legacy_id)
    for _ in range(2):
        report = user.get(f"/api/v1/tasks/{task_id}/results")
        assert report.status_code == 200
        assert report.json()["content"] == legacy["content"]
        assert report.json()["execution_kind"] == "legacy_single_call"
        assert report.json()["controller_mode"] == controller
        response = user.get(f"/api/v1/tasks/{task_id}/agent-steps")
        assert response.status_code == 200
        actions = response.json()
        assert actions["availability"] == "legacy" and actions["items"] == []
        assert collection.find_one({"_id": legacy_id}) == legacy


def test_rejected_numeric_material_never_exposes_uncommitted_actions(user, stores):
    task_id = submit(user, "目标：[stats]\n材料：1e6")["id"]

    def failed():
        response = user.get(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        assert task["status"] != "succeeded"
        return task if task["status"] == "failed" else None

    task = eventually(failed)
    assert task["attempt_count"] == 1 and task["error"]["code"] == "agent_tool_rejected"
    stored = rows(stores, "SELECT * FROM tasks WHERE id=:id", id=task_id)[0]
    assert stored["result_id"] is None
    assert stores["mongo"].agent_lab.results.count_documents({"task_id": task_id}) == 0
    response = user.get(f"/api/v1/tasks/{task_id}/agent-steps")
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "availability": "not_committed",
        "execution_kind": None,
        "controller_mode": None,
    }
    assert user.get(f"/api/v1/tasks/{task_id}/results").status_code == 409
