"""Shared local component experiments, deliberately separate from Agent tasks."""

import json

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from backend.db import LabKafkaMessage, LabRecord, now
from backend.lab_schema import LAB_GROUP, LAB_KAFKA_ENVELOPE_BYTES, LAB_TOPIC, KafkaInput
from backend.service import ServiceError, iso, uid


def not_found():
    return ServiceError(404, "not_found", "教学记录不存在")


def page(items, total, limit, offset):
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def record_view(row):
    return {
        "id": row.id, "name": row.name, "value": row.value,
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }


def document_view(row):
    return {
        "id": row["_id"], "document": row["document"],
        "created_at": iso(row["created_at"]), "updated_at": iso(row["updated_at"]),
    }


def kafka_view(row):
    return {
        "id": row.id, "topic": LAB_TOPIC, "key": row.key, "value": row.value,
        "created_at": iso(row.created_at), "observed_at": iso(now()),
        "producer": {
            "status": "acknowledged" if row.producer_acknowledged_at is not None else "unconfirmed",
            "acknowledged_at": iso(row.producer_acknowledged_at)
            if row.producer_acknowledged_at is not None else None,
            "partition": row.producer_partition, "offset": row.producer_offset,
        },
        "consumer": {
            "status": "received" if row.consumer_received_at is not None else "not_observed",
            "received_at": iso(row.consumer_received_at) if row.consumer_received_at is not None else None,
            "group": LAB_GROUP, "partition": row.consumer_partition, "offset": row.consumer_offset,
            "key": row.consumer_key, "value": row.consumer_value,
        },
    }


class PlaygroundService:
    def __init__(self, sessions, documents, kv, messages):
        self.sessions, self.documents, self.kv, self.messages = sessions, documents, kv, messages

    def mysql_create(self, name, value):
        record_id, instant = uid(), now()
        with self.sessions() as session, session.begin():
            session.add(LabRecord(id=record_id, name=name, value=value, created_at=instant, updated_at=instant))
        return self.mysql_get(record_id)  # A committed SQL read, not an echo of the request.

    def mysql_get(self, record_id):
        with self.sessions() as session:
            row = session.get(LabRecord, record_id)
            if row is None:
                raise not_found()
            return record_view(row)

    def mysql_list(self, limit, offset):
        with self.sessions() as session:
            rows = session.scalars(
                select(LabRecord).order_by(LabRecord.created_at.desc(), LabRecord.id.desc())
                .limit(limit).offset(offset)
            ).all()
            total = session.scalar(select(func.count()).select_from(LabRecord))
            return page([record_view(row) for row in rows], total, limit, offset)

    def mysql_replace(self, record_id, name, value):
        with self.sessions() as session, session.begin():
            row = session.get(LabRecord, record_id)
            if row is None:
                raise not_found()
            row.name, row.value, row.updated_at = name, value, now()
        return self.mysql_get(record_id)

    def mysql_delete(self, record_id):
        with self.sessions() as session, session.begin():
            row = session.get(LabRecord, record_id)
            if row is None:
                raise not_found()
            session.delete(row)

    def _mongo(self, operation, *args):
        try:
            return getattr(self.documents, operation)(*args)
        except Exception as exc:
            raise ServiceError(503, "document_unavailable", "MongoDB 教学文档暂不可用；写入结果可能不确定") from exc

    def _mongo_readback(self, document_id):
        row = self._mongo("get", document_id)
        if row is None:
            raise ServiceError(503, "document_unavailable", "无法确认写后读取，请按记录 ID 再次查询")
        return document_view(row)

    def mongo_create(self, document):
        document_id, instant = uid(), now()
        self._mongo("create", {
            "_id": document_id, "document": document, "created_at": instant, "updated_at": instant,
        })
        return self._mongo_readback(document_id)

    def mongo_get(self, document_id):
        row = self._mongo("get", document_id)
        if row is None:
            raise not_found()
        return document_view(row)

    def mongo_list(self, limit, offset):
        rows, total = self._mongo("listing", limit, offset)
        return page([document_view(row) for row in rows], total, limit, offset)

    def mongo_replace(self, document_id, document):
        if not self._mongo("replace", document_id, document, now()):
            raise not_found()
        return self._mongo_readback(document_id)

    def mongo_delete(self, document_id):
        if not self._mongo("delete", document_id):
            raise not_found()

    def redis_snapshot(self, key, value=None, ttl_seconds=None):
        try:
            stored, ttl = self.kv.snapshot(key, value, ttl_seconds)
        except Exception as exc:
            raise ServiceError(503, "redis_unavailable", "Redis 实验暂不可用；写入结果可能不确定") from exc
        return {
            "key": key, "exists": stored is not None, "value": stored,
            "ttl_ms": ttl, "observed_at": iso(now()),
        }

    def redis_delete(self, key):
        try:
            self.kv.delete(key)
        except Exception as exc:
            raise ServiceError(503, "redis_unavailable", "Redis 实验暂不可用；删除结果可能不确定") from exc

    def kafka_get(self, message_id):
        with self.sessions() as session:
            row = session.get(LabKafkaMessage, message_id)
            if row is None:
                raise not_found()
            return kafka_view(row)

    def kafka_list(self, limit, offset):
        with self.sessions() as session:
            rows = session.scalars(
                select(LabKafkaMessage).order_by(LabKafkaMessage.created_at.desc(), LabKafkaMessage.id.desc())
                .limit(limit).offset(offset)
            ).all()
            total = session.scalar(select(func.count()).select_from(LabKafkaMessage))
            return page([kafka_view(row) for row in rows], total, limit, offset)

    def _same_message(self, row, key, value):
        if row.key != key or row.value != value:
            raise ServiceError(409, "message_id_conflict", "消息 ID 已用于不同内容；未再次发送")
        return kafka_view(row)

    def kafka_send(self, message_id, key, value):
        try:
            with self.sessions() as session, session.begin():
                row = session.get(LabKafkaMessage, message_id)
                if row is not None:
                    return self._same_message(row, key, value), False
                session.add(LabKafkaMessage(id=message_id, key=key, value=value, created_at=now()))
        except IntegrityError:
            # Concurrent same-ID registrations: only the committed winner may publish.
            with self.sessions() as session:
                row = session.get(LabKafkaMessage, message_id)
                if row is None:
                    raise
                return self._same_message(row, key, value), False
        event = {"schema_version": 1, "id": message_id, "key": key, "value": value}
        try:
            partition, offset = self.messages.publish(event)
        except Exception as exc:
            raise ServiceError(
                503, "kafka_publish_unconfirmed", "未确认消息发送结果；请按已知 ID 查询，勿盲目重发",
            ) from exc
        # No network operation is inside the SQL transaction. Update only producer facts;
        # a concurrently committed receipt must never be overwritten by this acknowledgement.
        with self.sessions() as session, session.begin():
            session.execute(update(LabKafkaMessage).where(LabKafkaMessage.id == message_id).values(
                producer_acknowledged_at=now(), producer_partition=partition, producer_offset=offset,
            ))
        return self.kafka_get(message_id), True

    def kafka_receive(self, topic, raw_key, raw_value, partition, offset):
        """Persist a valid actual receipt, or reject protocol-invalid data (not SQL errors)."""
        if (
            topic != LAB_TOPIC or not isinstance(raw_value, bytes)
            or len(raw_value) > LAB_KAFKA_ENVELOPE_BYTES or not isinstance(raw_key, bytes)
            or len(raw_key) > 64 or type(partition) is not int or type(offset) is not int
            or partition < 0 or offset < 0
        ):
            return False
        try:
            event = json.loads(raw_value)
            if (
                not isinstance(event, dict) or set(event) != {"schema_version", "id", "key", "value"}
                or type(event["schema_version"]) is not int or event["schema_version"] != 1
            ):
                return False
            body = KafkaInput.model_validate({name: event[name] for name in ("id", "key", "value")})
            key = raw_key.decode("ascii")
            if body.key != key:
                return False
        except (ValueError, TypeError, RecursionError, ValidationError):
            return False
        with self.sessions() as session, session.begin():
            row = session.get(LabKafkaMessage, str(body.id))
            if row is None or row.key != key or row.value != body.value:
                return False
            # First receipt is stable under duplicates or a failed offset commit.
            session.execute(update(LabKafkaMessage).where(
                LabKafkaMessage.id == row.id, LabKafkaMessage.consumer_received_at.is_(None),
            ).values(
                consumer_received_at=now(), consumer_partition=partition, consumer_offset=offset,
                consumer_key=key, consumer_value=body.value,
            ))
        return True
