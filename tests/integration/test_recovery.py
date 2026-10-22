"""Deterministic crash-window injection with REAL SQL/Kafka/Mongo/Redis.
Host runner stops worker first; only the MODEL is deterministic. No fake store.
"""

import json
import uuid

import pytest
from conftest import submit
from sqlalchemy import select

from backend.adapters import KafkaBus, Model, MongoDocuments, ProgressCache
from backend.config import Settings
from backend.db import Attempt, Inbox, Outbox, Task, connect, now
from backend.service import TaskService

pytestmark = pytest.mark.integration


@pytest.fixture
def service(stores):
    settings = Settings()
    assert settings.mode == "production" and settings.database_url.startswith("mysql")
    engine, sessions = connect(settings.database_url)
    service = TaskService(
        sessions,
        settings,
        MongoDocuments(settings.mongo_url),
        KafkaBus(settings.kafka_servers),
        Model(settings),
        ProgressCache(settings.redis_url),
    )
    yield service
    service.documents.client.close()
    engine.dispose()


def test_replay_ack_gap_and_expired_lease_fencing(user, service):
    task_id = submit(user)["id"]
    assert user.get(f"/api/v1/tasks/{task_id}/results").status_code == 409
    actions = user.get(f"/api/v1/tasks/{task_id}/agent-steps")
    assert actions.status_code == 200
    assert actions.json() == {
        "items": [],
        "availability": "not_committed",
        "execution_kind": None,
        "controller_mode": None,
    }
    with service.sessions() as session:
        outbox = session.scalar(select(Outbox).where(Outbox.task_id == task_id))
        event = json.loads(outbox.payload)
        assert outbox.sent_at is None
    # Simulate broker acknowledged but relay died before SQL sent_at.
    service.bus.publish(service.settings.topic, event)
    with service.sessions() as session:
        assert session.get(Outbox, event["event_id"]).sent_at is None
    service.relay_once()  # actual broker receives same event_id again
    assert service.receive(event) is True
    # Simulate durable inbox committed but consumer died before offset ACK.
    assert service.receive(event) is False
    with service.sessions() as session:
        assert session.get(Inbox, event["event_id"])
        assert session.get(Task, task_id).status == "ready"
    claimed = service.claim()
    assert claimed.id == task_id
    stale_document = service.model.run(claimed)  # Execute while lease budget is still valid.
    with service.sessions() as session, session.begin():
        session.get(Task, task_id).lease_until = now() - 1
    assert service.finalize(claimed, "must-not-commit") is False
    service.recover()
    with service.sessions() as session, session.begin():
        task = session.get(Task, task_id)
        assert task.status == "retry_wait"
        task.next_attempt_at = now() - 1
    service.recover()
    replacement = service.claim()
    assert replacement.id == task_id and replacement.fence > claimed.fence
    # Persist an old attempt document: orphan must never become committed result.
    stale_id = task_id + ":" + claimed.attempt_id
    service.documents.save(stale_id, stale_document)
    assert service.finalize(claimed, stale_id) is False
    result_id = task_id + ":" + replacement.attempt_id
    service.documents.save(result_id, service.model.run(replacement))
    assert service.finalize(replacement, result_id) is True
    assert service.finalize(claimed, stale_id) is False
    with service.sessions() as session:
        task = session.get(Task, task_id)
        assert task.result_id == result_id and task.status == "succeeded"
        assert task.attempt_count == 2
        assert session.get(Attempt, claimed.attempt_id).outcome == "lease_expired"
    assert user.get(f"/api/v1/tasks/{task_id}/results").status_code == 200
    actions = user.get(f"/api/v1/tasks/{task_id}/agent-steps").json()
    assert actions["availability"] == "committed"
    assert actions["items"]
    assert {step["attempt_id"] for step in actions["items"]} == {replacement.attempt_id}


def test_bounded_retry_emits_durable_dlq(user, service):
    from confluent_kafka import Consumer
    from conftest import eventually

    from backend.domain import TransientError

    class UnavailableModel:
        def run(self, task):
            raise TransientError("simulated model outage; never a fake store")

    task_id = submit(user)["id"]
    assert user.get(f"/api/v1/tasks/{task_id}/results").status_code == 409
    actions = user.get(f"/api/v1/tasks/{task_id}/agent-steps")
    assert actions.status_code == 200
    assert actions.json() == {
        "items": [],
        "availability": "not_committed",
        "execution_kind": None,
        "controller_mode": None,
    }
    with service.sessions() as session:
        event = json.loads(session.scalar(select(Outbox).where(Outbox.task_id == task_id)).payload)
    service.relay_once()
    service.receive(event)
    service.model = UnavailableModel()  # ONLY model dependency is replaced.
    for attempt in range(1, service.settings.max_attempts + 1):
        assert service.execute_once() is True
        with service.sessions() as session, session.begin():
            task = session.get(Task, task_id)
            assert task.attempt_count == attempt and task.result_id is None
            if attempt < service.settings.max_attempts:
                assert task.status == "retry_wait" and task.next_attempt_at > now()
                task.next_attempt_at = now() - 1
            else:
                assert task.status == "failed"
        service.recover()
    with service.sessions() as session:
        dead = session.scalars(
            select(Outbox).where(Outbox.task_id == task_id, Outbox.event_type == "task.failed")
        ).all()
        assert len(dead) == 1 and dead[0].sent_at is None
        event_id = dead[0].id
    service.relay_once()
    consumer = Consumer(
        {
            "bootstrap.servers": service.settings.kafka_servers,
            "group.id": "dlq-evidence-" + uuid.uuid4().hex,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([service.settings.dlq_topic])

    def received():
        msg = consumer.poll(1)
        return msg and not msg.error() and json.loads(msg.value())["event_id"] == event_id

    try:
        eventually(received, timeout=30)
    finally:
        consumer.close()
    assert user.get(f"/api/v1/tasks/{task_id}/results").status_code == 409
    actions = user.get(f"/api/v1/tasks/{task_id}/agent-steps")
    assert actions.status_code == 200
    assert actions.json() == {
        "items": [],
        "availability": "not_committed",
        "execution_kind": None,
        "controller_mode": None,
    }
