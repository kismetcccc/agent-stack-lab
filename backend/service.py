import hashlib
import json
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.db import Attempt, Inbox, Outbox, Task, TaskEvent, now
from backend.domain import PermanentError, transition
from backend.faults import pause_at


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


class ServiceError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class TaskService:
    def __init__(self, sessions, settings, documents, bus, model, cache):
        self.sessions, self.settings, self.documents, self.bus = sessions, settings, documents, bus
        self.model, self.cache = model, cache

    def audit(self, session, task, kind, component):
        session.add(
            TaskEvent(
                id=uid(),
                task_id=task.id,
                trace_id=task.trace_id,
                component=component,
                kind=kind,
                content=kind,
            )
        )

    def events(self, owner, task_id):
        with self.sessions() as session:
            self.owned(session, owner, task_id)
            rows = session.scalars(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id)
                .order_by(TaskEvent.created_at, TaskEvent.id)
                .limit(100)
            ).all()
            return {
                "items": [
                    {
                        "id": row.id,
                        "task_id": row.task_id,
                        "trace_id": row.trace_id,
                        "sequence": index + 1,
                        "kind": row.kind,
                        "component": row.component,
                        "content": row.content,
                        "created_at": iso(row.created_at),
                    }
                    for index, row in enumerate(rows)
                ]
            }

    def attempts(self, owner, task_id):
        with self.sessions() as session:
            self.owned(session, owner, task_id)
            rows = session.scalars(
                select(Attempt).where(Attempt.task_id == task_id).order_by(Attempt.started_at).limit(100)
            ).all()
            return {
                "items": [
                    {
                        "id": row.id,
                        "fence": row.fence,
                        "started_at": iso(row.started_at),
                        "finished_at": iso(row.finished_at) if row.finished_at else None,
                        "outcome": row.outcome,
                    }
                    for row in rows
                ]
            }

    def emit(self, session, task, event_type):
        event_id = uid()
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "schema_version": 1,
            "task_id": task.id,
            "occurred_at": iso(now()),
            "trace_id": task.trace_id,
        }
        session.add(Outbox(id=event_id, task_id=task.id, event_type=event_type, payload=json.dumps(event)))

    def create(self, owner, key, prompt, trace):
        # Hash opaque raw keys: MySQL collation/padding must not change key semantics.
        key = digest(key)
        request_hash = digest(prompt)
        try:
            with self.sessions() as session, session.begin():
                existing = session.scalar(
                    select(Task).where(Task.owner_id == owner, Task.idempotency_key == key)
                )
                if existing:
                    return self.same(existing, request_hash)
                task = Task(
                    id=uid(),
                    owner_id=owner,
                    idempotency_key=key,
                    request_hash=request_hash,
                    prompt=prompt,
                    trace_id=trace,
                    model_mode=self.settings.model_mode,
                )
                session.add(task)
                session.flush()
                self.emit(session, task, "task.created")
                self.audit(session, task, "pending", "api")
                return self.dto(task)
        except IntegrityError:
            # Concurrent same-key INSERT loser reads winner after transaction rollback.
            with self.sessions() as session:
                existing = session.scalar(
                    select(Task).where(Task.owner_id == owner, Task.idempotency_key == key)
                )
                if not existing:
                    raise
                return self.same(existing, request_hash)

    def same(self, task, request_hash):
        if task.request_hash != request_hash:
            raise ServiceError(409, "idempotency_conflict", "同一幂等键不能用于不同请求")
        return self.dto(task)

    def owned(self, session, owner, task_id):
        task = session.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner))
        if not task:
            raise ServiceError(404, "not_found", "任务不存在")
        return task

    def get(self, owner, task_id):
        with self.sessions() as session:
            return self.dto(self.owned(session, owner, task_id))

    def listing(self, owner, limit, offset):
        with self.sessions() as session:
            query = select(Task).where(Task.owner_id == owner)
            total = session.scalar(select(func.count()).select_from(Task).where(Task.owner_id == owner))
            items = session.scalars(
                query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).offset(offset)
            ).all()
            return {"items": [self.dto(t) for t in items], "total": total, "limit": limit, "offset": offset}

    def document(self, owner, task_id, steps=False):
        with self.sessions() as session:
            task = self.owned(session, owner, task_id)
            if task.status != "succeeded" or not task.result_id:
                if steps:
                    return {"items": []}
                raise ServiceError(409, "result_not_ready", "任务尚未成功")
            result_id = task.result_id
        try:
            doc, cache_status = self.cache.read_result(result_id)
            if doc is None:
                doc = self.documents.get(result_id)
                if doc is not None:
                    self.cache.store_result(result_id, doc)
        except Exception as exc:
            raise ServiceError(503, "document_unavailable", "结果存储暂不可用") from exc
        if not doc:
            raise ServiceError(503, "document_unavailable", "结果文档暂不可读")
        return (
            {"items": doc["steps"][:100]}
            if steps
            else {**{k: doc[k] for k in ("task_id", "content", "model_mode")}, "cache_status": cache_status}
        )

    def dto(self, task):
        return {
            "id": task.id,
            "prompt": task.prompt,
            "status": task.status,
            "attempt_count": task.attempt_count,
            "created_at": iso(task.created_at),
            "updated_at": iso(task.updated_at),
            "error": {"code": task.error_code, "message": "执行失败；错误信息已脱敏"}
            if task.error_code
            else None,
            "result_available": task.status == "succeeded" and bool(task.result_id),
            "model_mode": task.model_mode,
            "trace_id": task.trace_id,
            "progress": {"pending": 0, "ready": 10, "running": 30, "succeeded": 100}.get(task.status, 0),
        }

    def relay_once(self):
        # 首版只运行一个 relay；publish 与 sent 标记之间崩溃会重投相同 event_id。
        with self.sessions() as session:
            rows = session.scalars(select(Outbox).where(Outbox.sent_at.is_(None)).limit(50)).all()
        for row in rows:
            topic = self.settings.dlq_topic if row.event_type == "task.failed" else self.settings.topic
            self.bus.publish(topic, json.loads(row.payload))
            pause_at("after_outbox_publish")
            with self.sessions() as session, session.begin():
                stored = session.get(Outbox, row.id)
                stored.sent_at = now()
                task = session.get(Task, row.task_id)
                self.audit(session, task, "outbox_sent", "relay")
        return len(rows)

    def receive(self, event):
        if event.get("schema_version") != 1 or event.get("event_type") != "task.created":
            raise ValueError("unsupported event schema/type; offset must not advance")
        try:
            with self.sessions() as session, session.begin():
                session.add(Inbox(event_id=event["event_id"]))
                session.flush()
                task = session.scalar(select(Task).where(Task.id == event["task_id"]).with_for_update())
                if not task:
                    raise ValueError("unknown task; offset must not advance")
                if task.status == "pending":
                    transition(task, "ready")
                    self.audit(session, task, "ready", "consumer")
                    task.updated_at = now()
            return True
        except IntegrityError:
            with self.sessions() as session:
                if session.get(Inbox, event["event_id"]):
                    return False
            raise

    def claim(self):
        with self.sessions() as session, session.begin():
            task = session.scalar(
                select(Task)
                .where(Task.status == "ready")
                .order_by(Task.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not task:
                return None
            transition(task, "running")
            self.audit(session, task, "running", "executor")
            task.fence += 1
            task.attempt_count += 1
            task.attempt_id = uid()
            task.lease_until = now() + self.settings.lease_seconds
            task.updated_at = now()
            session.add(Attempt(id=task.attempt_id, task_id=task.id, fence=task.fence))
            session.flush()
            return task

    def finalize(self, claimed, result_id):
        with self.sessions() as session, session.begin():
            task = session.scalar(select(Task).where(Task.id == claimed.id).with_for_update())
            if task.status != "running" or task.fence != claimed.fence or task.lease_until <= now():
                return False
            transition(task, "succeeded")
            self.audit(session, task, "succeeded", "executor")
            task.result_id, task.updated_at, task.error_code = result_id, now(), None
            attempt = session.get(Attempt, claimed.attempt_id)
            attempt.finished_at, attempt.outcome = now(), "succeeded"
            return True

    def fail_locked(self, session, task, permanent=False, code="transient_failure"):
        terminal = permanent or task.attempt_count >= self.settings.max_attempts
        transition(task, "failed" if terminal else "retry_wait")
        self.audit(session, task, task.status, "recovery" if code == "lease_expired" else "executor")
        task.error_code, task.updated_at = code, now()
        task.next_attempt_at = now() + min(60, 2**task.attempt_count) + random.random()
        attempt = session.get(Attempt, task.attempt_id)
        if attempt:
            attempt.finished_at, attempt.outcome = now(), code
        if terminal:
            self.emit(session, task, "task.failed")

    def execute_once(self):
        claimed = self.claim()
        if not claimed:
            return False
        pause_at("after_claim")
        self.cache.write(claimed.id, "running")
        try:
            result_id = claimed.id + ":" + claimed.attempt_id
            # Immutable attempt-specific document. Never expose an orphan as committed success.
            doc = self.documents.get(result_id)
            if not doc:
                doc = self.model.run(claimed)
                self.documents.save(result_id, doc)
                pause_at("after_mongo_save")
            self.finalize(claimed, result_id)
        except Exception as exc:
            with self.sessions() as session, session.begin():
                task = session.scalar(select(Task).where(Task.id == claimed.id).with_for_update())
                if task.status == "running" and task.fence == claimed.fence and task.lease_until > now():
                    self.fail_locked(
                        session,
                        task,
                        isinstance(exc, PermanentError),
                        "permanent_failure" if isinstance(exc, PermanentError) else "transient_failure",
                    )
        return True

    def recover(self):
        with self.sessions() as session, session.begin():
            expired = session.scalars(
                select(Task)
                .where(Task.status == "running", Task.lease_until <= now())
                .with_for_update(skip_locked=True)
                .limit(100)
            ).all()
            for task in expired:
                self.fail_locked(session, task, code="lease_expired")
            due = session.scalars(
                select(Task)
                .where(Task.status == "retry_wait", Task.next_attempt_at <= now())
                .with_for_update(skip_locked=True)
                .limit(100)
            ).all()
            for task in due:
                transition(task, "ready")
                self.audit(session, task, "ready", "recovery")
                task.updated_at = now()
