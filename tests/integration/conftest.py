"""Black-box HTTP + real-store acceptance. Never accepts SQLite/in-memory adapters."""

import json
import os
import time
import uuid

import httpx
import pytest
from pymongo import MongoClient
from redis import Redis
from sqlalchemy import create_engine, text


def eventually(check, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (httpx.HTTPError, AssertionError) as exc:
            last = exc
        time.sleep(0.5)
    raise AssertionError(f"condition not reached within {timeout}s; last={last}")


@pytest.fixture(scope="session")
def base_url():
    return os.getenv("TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def stores():
    url = os.environ["DATABASE_URL"]
    assert url.startswith("mysql"), "integration MUST use real MySQL"
    assert os.getenv("LAB_MODE", "production") == "production"
    engine = create_engine(url, pool_pre_ping=True)
    mongo = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)
    redis = Redis.from_url(os.environ["REDIS_URL"], socket_timeout=3)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT VERSION()")).scalar()
    mongo.admin.command("ping")
    assert redis.ping()
    yield {"sql": engine, "mongo": mongo, "redis": redis}
    engine.dispose()
    mongo.close()
    redis.close()


@pytest.fixture
def user(base_url):
    username = "it_" + uuid.uuid4().hex[:20]
    password = "Integration-only!42-" + uuid.uuid4().hex
    with httpx.Client(base_url=base_url, timeout=15) as client:
        response = client.post("/api/v1/auth/register", json={"username": username, "password": password})
        assert response.status_code in (200, 201), response.text
        token = response.json()["csrf_token"]
        client.headers["X-CSRF-Token"] = token
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.post("/api/v1/auth/logout").status_code == 204
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client


def submit(client, prompt="Explain durable outbox delivery", key=None):
    response = client.post(
        "/api/v1/tasks", json={"prompt": prompt}, headers={"Idempotency-Key": key or str(uuid.uuid4())}
    )
    assert response.status_code == 202, response.text
    return response.json()


def completed(client, task_id):
    def probe():
        response = client.get(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["status"] != "failed", task
        return task if task["status"] == "succeeded" else None

    return eventually(probe)


def rows(stores, query, **params):
    with stores["sql"].connect() as conn:
        return [dict(row) for row in conn.execute(text(query), params).mappings()]


def envelope(stores, task_id):
    return json.loads(
        rows(
            stores, "SELECT payload FROM outbox WHERE task_id=:id AND event_type='task.created'", id=task_id
        )[0]["payload"]
    )
