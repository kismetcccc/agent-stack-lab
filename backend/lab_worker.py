"""Dedicated fixed-topic observer: commit durable receipts before Kafka offsets."""

import logging

from backend.lab_schema import LAB_GROUP, LAB_TOPIC

log = logging.getLogger("lab_observer")


def observe_one(runtime, consumer, message):
    if message.error():
        raise RuntimeError("Kafka lab poll error")
    accepted = runtime.lab.kafka_receive(
        message.topic(), message.key(), message.value(), message.partition(), message.offset(),
    )
    if not accepted:
        # Invalid/unregistered protocol data is not a storage error and must not poison
        # the fixed observer. Never log keys, values, or exception text.
        log.warning("lab_message_rejected code=invalid_or_unregistered")
    # kafka_receive has committed, or intentionally rejected the protocol record.
    # Any persistence exception escapes WITHOUT committing this or later offsets.
    results = consumer.commit(message=message, asynchronous=False)
    if results and any(result.error is not None for result in results):
        raise RuntimeError("Kafka lab offset commit unconfirmed")


def consume_lab_messages(runtime, stop, consumer_factory=None):
    if consumer_factory is None:
        from confluent_kafka import Consumer

        consumer_factory = Consumer
    while not stop.is_set():
        consumer = None
        try:
            consumer = consumer_factory({
                "bootstrap.servers": runtime.settings.kafka_servers,
                "group.id": LAB_GROUP,
                "enable.auto.commit": False,
                "enable.auto.offset.store": False,
                "auto.offset.reset": "earliest",
                "socket.timeout.ms": 5000,
            })
            consumer.subscribe([LAB_TOPIC])
            while not stop.is_set():
                message = consumer.poll(0.5)
                if message is not None:
                    observe_one(runtime, consumer, message)
        except Exception as exc:
            log.error("lab_observer_reconnect type=%s", type(exc).__name__)
        finally:
            if consumer is not None:
                try:
                    consumer.close()
                except Exception as exc:
                    log.error("lab_observer_close_failed type=%s", type(exc).__name__)
        # Recreate from the committed offset, rather than polling past a failed receipt.
        # This is consumer recovery, NOT a producer republish/replay API.
        stop.wait(1)
