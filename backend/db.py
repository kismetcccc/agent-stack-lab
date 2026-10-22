"""关系数据：事务、唯一约束及索引是正确性的基础，不依赖进程内锁。"""

from datetime import UTC, datetime

from sqlalchemy import Double, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def now():
    return datetime.now(UTC).timestamp()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Double)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key"),
        Index("ix_task_queue", "status", "next_attempt_at"),
        Index("ix_task_owner_created", "owner_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(
        String(128).with_variant(String(128, collation="utf8mb4_bin"), "mysql")
    )
    request_hash: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float] = mapped_column(Double, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Double, default=0)
    result_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[float] = mapped_column(Double, default=now)
    updated_at: Mapped[float] = mapped_column(Double, default=now)
    model_mode: Mapped[str] = mapped_column(String(20), default="deterministic")


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[float | None] = mapped_column(Double, nullable=True, index=True)


class Inbox(Base):
    __tablename__ = "inbox"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    received_at: Mapped[float] = mapped_column(Double, default=now)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    fence: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[float] = mapped_column(Double, default=now)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), default="running")


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)


def connect(url):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    elif url.startswith("mysql+pymysql"):
        kwargs["connect_args"] = {"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5}
    engine = create_engine(url, **kwargs)
    return engine, sessionmaker(engine, expire_on_commit=False)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (Index("ix_event_task_time", "task_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36))
    trace_id: Mapped[str] = mapped_column(String(36))
    component: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[float] = mapped_column(Double, default=now)
