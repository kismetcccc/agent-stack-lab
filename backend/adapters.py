"""真实适配器与显式 test/demo 适配器，网络调用不能位于 SQL 事务中。"""

import asyncio
import json

from backend.domain import TransientError


class MemoryDocuments:
    def __init__(self):
        self.docs = {}

    def save(self, result_id, document):
        self.docs.setdefault(result_id, document)

    def get(self, result_id):
        return self.docs.get(result_id)

    def ping(self):
        return True


class MongoDocuments:
    def __init__(self, url):
        from pymongo import MongoClient

        self.client = MongoClient(
            url, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000, socketTimeoutMS=3000, timeoutMS=5000
        )
        self.collection = self.client.agent_lab.results

    def save(self, result_id, document):
        self.collection.update_one({"_id": result_id}, {"$setOnInsert": document}, upsert=True)

    def get(self, result_id):
        return self.collection.find_one({"_id": result_id}, {"_id": 0})

    def ping(self):
        return self.client.admin.command("ping")["ok"] == 1


class MemoryBus:
    def __init__(self):
        self.messages = []

    def publish(self, topic, event):
        self.messages.append((topic, event))

    def ping(self):
        return True


class KafkaBus:
    def __init__(self, servers):
        self.servers = servers
        self._producer = None

    @property
    def producer(self):
        if self._producer is None:
            from confluent_kafka import Producer

            self._producer = Producer(
                {"bootstrap.servers": self.servers, "enable.idempotence": True, "delivery.timeout.ms": 10000}
            )
        return self._producer

    def ensure_topics(self, topics):
        from confluent_kafka import KafkaError, KafkaException
        from confluent_kafka.admin import AdminClient, NewTopic

        admin = AdminClient({"bootstrap.servers": self.servers})
        futures = admin.create_topics(
            [NewTopic(topic, num_partitions=1, replication_factor=1) for topic in topics], request_timeout=10
        )
        for future in futures.values():
            try:
                future.result(timeout=15)
            except KafkaException as exc:
                if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise

    def publish(self, topic, event):
        errors = []
        self.producer.produce(
            topic, key=event["task_id"], value=json.dumps(event), callback=lambda err, msg: errors.append(err)
        )
        remaining = self.producer.flush(12)
        if remaining or not errors or errors[0]:
            raise TransientError("Kafka delivery not acknowledged")

    def ping(self):
        return bool(self.producer.list_topics(timeout=2).brokers)


class Model:
    def __init__(self, settings):
        self.settings = settings

    def run(self, task):
        from backend.agent import ScriptedController, run_agent
        from backend.agent_errors import AgentConfigurationError
        from backend.agent_provider import LiveController

        if task.model_mode != self.settings.model_mode:
            raise AgentConfigurationError("task model mode differs from worker configuration")
        if self.settings.model_mode == "deterministic":
            controller = ScriptedController()
        elif self.settings.model_mode == "live":
            controller = LiveController(self.settings)
        else:
            raise AgentConfigurationError("unsupported model mode")
        return asyncio.run(run_agent(task, controller))


class ProgressCache:
    def __init__(self, url):
        self.client = None
        if url:
            from redis import Redis

            self.client = Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)

    def write(self, task_id, phase):
        if self.client:
            try:
                self.client.setex("progress:" + task_id, 300, phase)
            except Exception:
                pass  # 可丢弃进度绝不控制权威状态。

    def read_result(self, result_id):
        if not self.client:
            return None, "disabled"
        try:
            raw = self.client.get("result:" + result_id)
            return (json.loads(raw), "hit") if raw else (None, "miss")
        except Exception:
            return None, "unavailable"

    def store_result(self, result_id, document):
        if self.client:
            try:
                self.client.setex("result:" + result_id, 300, json.dumps(document))
            except Exception:
                return False
        return True
