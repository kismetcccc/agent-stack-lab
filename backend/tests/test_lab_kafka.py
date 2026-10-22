"""Offline protocol/concurrency/observer tests; no real broker is claimed here."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.config import Settings
from backend.db import LabKafkaMessage, now
from backend.lab_adapters import KafkaLabMessages
from backend.lab_schema import LAB_GROUP, LAB_TOPIC
from backend.lab_worker import consume_lab_messages, observe_one
from backend.migrate import migrate
from backend.runtime import Runtime
from backend.service import ServiceError


@pytest.fixture
def runtime():
    value = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///:memory:"))
    migrate(value.engine)
    yield value
    value.engine.dispose()


def registered(runtime, **changes):
    event = {"schema_version": 1, "id": str(uuid4()), "key": "lesson", "value": "actual payload"} | changes
    with runtime.sessions() as session, session.begin():
        session.add(LabKafkaMessage(id=event["id"], key=event["key"], value=event["value"], created_at=now()))
    return event


def receive(runtime, event, **changes):
    args = {"topic": LAB_TOPIC, "raw_key": event["key"].encode(), "raw_value": json.dumps(event).encode(),
            "partition": 0, "offset": 7} | changes
    return runtime.lab.kafka_receive(**args)


def test_actual_receipt_is_independent_of_producer_status_and_first_receipt_is_stable(runtime):
    event = registered(runtime)
    assert receive(runtime, event)
    first = runtime.lab.kafka_get(event["id"])
    assert first["producer"] == {"status": "unconfirmed", "acknowledged_at": None, "partition": None, "offset": None}
    assert first["consumer"]["status"] == "received"
    assert first["consumer"]["key"] == event["key"] and first["consumer"]["value"] == event["value"]
    assert first["consumer"]["offset"] == 7 and first["consumer"]["group"] == LAB_GROUP
    assert receive(runtime, event, offset=8)
    assert runtime.lab.kafka_get(event["id"])["consumer"] == first["consumer"]


def test_producer_ack_cannot_overwrite_receipt_that_arrived_during_publish(runtime, monkeypatch):
    def publish(event):
        assert receive(runtime, event, offset=15)
        return 0, 15

    monkeypatch.setattr(runtime.lab.messages, "publish", publish)
    snapshot, created = runtime.lab.kafka_send(str(uuid4()), "lesson", "payload")
    assert created and snapshot["producer"]["status"] == "acknowledged"
    assert snapshot["consumer"]["status"] == "received" and snapshot["consumer"]["offset"] == 15


def test_uncertain_publish_retains_record_and_retry_never_resends(runtime, monkeypatch):
    calls = []

    def uncertain(event):
        calls.append(event)
        # Receipt may happen even if producer acknowledgement is lost.
        assert receive(runtime, event)
        raise TimeoutError("private broker endpoint")

    monkeypatch.setattr(runtime.lab.messages, "publish", uncertain)
    message_id = str(uuid4())
    with pytest.raises(ServiceError) as caught:
        runtime.lab.kafka_send(message_id, "lesson", "payload")
    assert caught.value.code == "kafka_publish_unconfirmed"
    snapshot, created = runtime.lab.kafka_send(message_id, "lesson", "payload")
    assert not created and len(calls) == 1
    assert snapshot["producer"]["status"] == "unconfirmed" and snapshot["consumer"]["status"] == "received"
    with pytest.raises(ServiceError) as conflict:
        runtime.lab.kafka_send(message_id, "lesson", "different")
    assert conflict.value.code == "message_id_conflict" and len(calls) == 1


def test_failed_ack_write_keeps_persisted_registration_and_no_second_publish(runtime, monkeypatch):
    original_sessions = runtime.lab.sessions
    calls = []

    def sql_down():
        raise SQLAlchemyError("private SQL address")

    def publish(event):
        calls.append(event)
        monkeypatch.setattr(runtime.lab, "sessions", sql_down)
        return 0, 33

    monkeypatch.setattr(runtime.lab.messages, "publish", publish)
    message_id = str(uuid4())
    with pytest.raises(SQLAlchemyError):
        runtime.lab.kafka_send(message_id, "lesson", "payload")
    monkeypatch.setattr(runtime.lab, "sessions", original_sessions)
    snapshot, created = runtime.lab.kafka_send(message_id, "lesson", "payload")
    assert not created and snapshot["producer"]["status"] == "unconfirmed" and len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"topic": "agent.tasks"}, {"raw_value": b"bad JSON"}, {"raw_value": b"x" * 32769},
    {"raw_value": b"[]"}, {"raw_key": None}, {"raw_key": b"different"}, {"raw_key": b"\xff"},
    {"raw_key": b"x" * 65}, {"partition": -1}, {"offset": -1}, {"offset": True},
])
def test_bad_transport_or_protocol_never_invents_receipt(runtime, changes):
    event = registered(runtime)
    assert not receive(runtime, event, **changes)
    assert runtime.lab.kafka_get(event["id"])["consumer"]["status"] == "not_observed"


@pytest.mark.parametrize("changes", [
    {"schema_version": 2}, {"schema_version": True}, {"id": "bad"},
    {"value": "changed"}, {"value": ""}, {"value": "x" * 4097},
    {"id": str(uuid4())}, {"extra": "no"}, {"topic": LAB_TOPIC},
])
def test_invalid_or_unregistered_envelopes_are_rejected_without_receipts(runtime, changes):
    event = registered(runtime)
    bad = event | changes
    assert not receive(runtime, event, raw_value=json.dumps(bad).encode())
    assert runtime.lab.kafka_get(event["id"])["consumer"]["status"] == "not_observed"


def test_receipt_storage_exception_is_not_classified_as_invalid_protocol(runtime, monkeypatch):
    event = registered(runtime)

    def unavailable():
        raise SQLAlchemyError("offline")

    monkeypatch.setattr(runtime.lab, "sessions", unavailable)
    with pytest.raises(SQLAlchemyError):
        receive(runtime, event)


def test_concurrent_identical_registration_has_one_producer_call(tmp_path):
    runtime = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///" + str(tmp_path / "concurrent.db")))
    try:
        migrate(runtime.engine)
        message_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: runtime.lab.kafka_send(message_id, "lesson", "same"), range(8)))
        assert sum(created for _, created in results) == 1
        assert len(runtime.lab.messages.messages) == 1
        with runtime.sessions() as session:
            assert len(session.scalars(select(LabKafkaMessage)).all()) == 1
    finally:
        runtime.engine.dispose()


def message(event):
    return SimpleNamespace(
        error=lambda: None, topic=lambda: LAB_TOPIC, key=lambda: event["key"].encode(),
        value=lambda: json.dumps(event).encode(), partition=lambda: 0, offset=lambda: 7,
    )


def test_observer_persists_before_synchronous_offset_commit(runtime):
    event = registered(runtime)
    consumer = Mock()

    def commit(**kwargs):
        assert kwargs["asynchronous"] is False
        assert runtime.lab.kafka_get(event["id"])["consumer"]["status"] == "received"
        return [SimpleNamespace(error=None)]

    consumer.commit.side_effect = commit
    observe_one(runtime, consumer, message(event))
    consumer.commit.assert_called_once()


def test_observer_never_commits_storage_failure_but_commits_invalid_record(runtime, monkeypatch):
    event = registered(runtime)
    consumer = Mock()
    consumer.commit.return_value = []
    monkeypatch.setattr(runtime.lab, "kafka_receive", Mock(side_effect=SQLAlchemyError("offline")))
    with pytest.raises(SQLAlchemyError):
        observe_one(runtime, consumer, message(event))
    consumer.commit.assert_not_called()
    monkeypatch.setattr(runtime.lab, "kafka_receive", lambda *args: False)
    observe_one(runtime, consumer, message(event))
    consumer.commit.assert_called_once()


def test_observer_reconnects_on_returned_offset_error_without_polling_past_record(runtime):
    event = registered(runtime)
    stop = threading.Event()
    first, second = Mock(), Mock()
    first.poll.return_value = message(event)
    first.commit.return_value = [SimpleNamespace(error=RuntimeError("unconfirmed"))]
    second.commit.return_value = [SimpleNamespace(error=None)]

    def next_message(timeout):
        stop.set()
        return message(event)

    second.poll.side_effect = next_message
    factory = Mock(side_effect=[first, second])
    # Avoid a real second delay while retaining the stop/reconnect behavior.
    stop.wait = Mock(return_value=False)
    consume_lab_messages(runtime, stop, factory)
    assert factory.call_count == 2
    first.poll.assert_called_once()  # Never advance past the failed offset.
    first.close.assert_called_once()
    second.close.assert_called_once()
    first.subscribe.assert_called_once_with([LAB_TOPIC])
    config = factory.call_args_list[0].args[0]
    assert config["group.id"] == LAB_GROUP
    assert config["enable.auto.commit"] is False and config["enable.auto.offset.store"] is False
    assert runtime.lab.kafka_get(event["id"])["consumer"]["offset"] == 7


@pytest.mark.parametrize("case", ["remaining", "no_callback", "error", "bad_metadata"])
def test_producer_requires_delivery_callback_and_actual_metadata(case):
    class Producer:
        def produce(self, topic, **kwargs):
            assert topic == LAB_TOPIC and kwargs["key"] == "lesson"
            assert json.loads(kwargs["value"])["value"] == "你好"
            if case not in {"no_callback", "remaining"}:
                kwargs["callback"](RuntimeError("not ack") if case == "error" else None,
                                   SimpleNamespace(partition=lambda: 0, offset=lambda: -1 if case == "bad_metadata" else 9))

        def flush(self, timeout):
            assert timeout == 12
            return 1 if case == "remaining" else 0

    bus = KafkaLabMessages(SimpleNamespace(producer=Producer()))
    with pytest.raises(ConnectionError):
        bus.publish({"schema_version": 1, "id": str(uuid4()), "key": "lesson", "value": "你好"})


@pytest.mark.parametrize("other_pending", [0, 2])
def test_producer_returns_own_callback_metadata_despite_unrelated_pending_sends(other_pending):
    producer = Mock()
    producer.produce.side_effect = lambda topic, **kwargs: kwargs["callback"](
        None, SimpleNamespace(partition=lambda: 3, offset=lambda: 2**35),
    )
    producer.flush.return_value = other_pending
    bus = KafkaLabMessages(SimpleNamespace(producer=producer))
    assert bus.publish({"schema_version": 1, "id": str(uuid4()), "key": "lesson", "value": "hi"}) == (3, 2**35)


@pytest.mark.parametrize("field", ["topic", "dlq_topic"])
def test_task_topic_configuration_cannot_collide_with_reserved_lab_protocol(field):
    with pytest.raises(ValueError, match="reserved lab topic"):
        Settings(**{field: LAB_TOPIC})


def test_other_existing_topic_settings_remain_configurable():
    settings = Settings(topic="custom.tasks", dlq_topic="custom.tasks.dlq")
    assert settings.topic == "custom.tasks" and settings.dlq_topic == "custom.tasks.dlq"
