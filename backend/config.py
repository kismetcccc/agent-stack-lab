import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = os.getenv("LAB_MODE", "production")
    database_url: str = os.getenv("DATABASE_URL", "mysql+pymysql://lab:change-me@localhost:3306/agentlab")
    mongo_url: str = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    kafka_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    redis_url: str = os.getenv("REDIS_URL", "")
    origin: str = os.getenv("APP_ORIGIN", "http://localhost:8080")
    secure_cookie: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    model_mode: str = os.getenv("MODEL_MODE", "deterministic")
    live_enabled: bool = os.getenv("ALLOW_LIVE_MODEL", "false").lower() == "true"
    lease_seconds: int = int(os.getenv("LEASE_SECONDS", "120"))
    max_attempts: int = int(os.getenv("MAX_ATTEMPTS", "3"))
    topic: str = os.getenv("KAFKA_TOPIC", "agent.tasks")
    dlq_topic: str = os.getenv("KAFKA_DLQ_TOPIC", "agent.tasks.dlq")

    def __post_init__(self):
        if self.model_mode not in {"deterministic", "live"}:
            raise ValueError("MODEL_MODE must be deterministic/live")
        if self.lease_seconds <= 0 or not 1 <= self.max_attempts <= 100:
            raise ValueError("LEASE_SECONDS must be positive; MAX_ATTEMPTS must be 1..100")
        if self.mode not in {"production", "test", "demo"}:
            raise ValueError("LAB_MODE must be production/test/demo")
        if self.database_url.startswith("sqlite") and self.mode == "production":
            raise ValueError("SQLite is only permitted in explicitly labelled test/demo mode")
