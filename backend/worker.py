"""单 Worker 首版：短 poll 持久化 inbox 后同步提交该 offset；独立 executor 执行长任务。"""

import json
import logging
import sys
import threading
import time
from pathlib import Path

from backend.faults import pause_at
from backend.lab_schema import LAB_TOPIC
from backend.lab_worker import consume_lab_messages
from backend.migrate import assert_current_schema
from backend.runtime import Runtime

HEARTBEAT = Path("/tmp/worker-heartbeat")
log = logging.getLogger("worker")


def executor(runtime, stop):
    while not stop.is_set():
        try:
            runtime.tasks.recover()
            if not runtime.tasks.execute_once():
                stop.wait(0.25)
        except Exception as exc:
            log.error("executor_failed type=%s", type(exc).__name__)
            stop.wait(1)


def relay(runtime, stop):
    while not stop.is_set():
        try:
            runtime.tasks.relay_once()
        except Exception as exc:
            log.error("relay_failed type=%s", type(exc).__name__)
        stop.wait(0.5)


def main():
    if "--healthcheck" in sys.argv:
        sys.exit(0 if HEARTBEAT.exists() and time.time() - HEARTBEAT.stat().st_mtime < 30 else 1)
    logging.basicConfig(level=logging.INFO)
    runtime = Runtime()
    if runtime.settings.mode != "production":
        raise SystemExit(
            "Independent Worker needs real services; test/demo uses in-process explicit tick only"
        )
    assert_current_schema(runtime.engine)
    runtime.bus.ensure_topics([runtime.settings.topic, runtime.settings.dlq_topic, LAB_TOPIC])
    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": runtime.settings.kafka_servers,
            "group.id": "agent-executors-v1",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([runtime.settings.topic])
    stop = threading.Event()
    thread = threading.Thread(target=executor, args=(runtime, stop), daemon=True)
    thread.start()
    relay_thread = threading.Thread(target=relay, args=(runtime, stop), daemon=True)
    relay_thread.start()
    lab_thread = threading.Thread(target=consume_lab_messages, args=(runtime, stop), daemon=True)
    lab_thread.start()
    try:
        while True:
            message = consumer.poll(0.5)
            if message:
                if message.error():
                    raise RuntimeError("Kafka consume error")
                # If persist or commit fails, stop loop and restart rather than polling past an uncommitted record.
                event = json.loads(message.value())
                runtime.tasks.receive(event)
                pause_at(
                    "after_inbox_commit", event["task_id"], event_id=event["event_id"],
                    topic=message.topic(), partition=message.partition(), offset=message.offset(),
                )
                consumer.commit(message=message, asynchronous=False)
            HEARTBEAT.touch()
    finally:
        stop.set()
        consumer.close()
        thread.join(timeout=35)
        relay_thread.join(timeout=15)
        lab_thread.join(timeout=10)


if __name__ == "__main__":
    main()
