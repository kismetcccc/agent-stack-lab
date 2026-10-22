"""Isolated fixed lab operations. Production never falls back to a test adapter."""

import copy
import json
import threading
import time

from backend.lab_schema import LAB_REDIS_PREFIX, LAB_TOPIC

# These scripts are fixed application code, never accepted from the HTTP caller.
REDIS_READ = "local v=redis.call('GET',KEYS[1]); return {v or false,redis.call('PTTL',KEYS[1])}"
REDIS_WRITE = "redis.call('SET',KEYS[1],ARGV[1],'PX',ARGV[2]); " + REDIS_READ


class RedisLabKV:
    def __init__(self, client):
        self.client = client

    def snapshot(self, key, value=None, ttl_seconds=None):
        if self.client is None:
            raise ConnectionError("Redis lab is not configured")
        full_key = LAB_REDIS_PREFIX + key
        raw, ttl = (
            self.client.eval(REDIS_READ, 1, full_key)
            if ttl_seconds is None
            else self.client.eval(REDIS_WRITE, 1, full_key, value, ttl_seconds * 1000)
        )
        return (raw.decode("utf-8") if raw is not None else None), int(ttl)

    def delete(self, key):
        if self.client is None:
            raise ConnectionError("Redis lab is not configured")
        self.client.delete(LAB_REDIS_PREFIX + key)


class MongoLabDocuments:
    def __init__(self, client):
        self.collection = client.agent_lab.lab_documents

    def create(self, row):
        self.collection.insert_one(row)

    def get(self, document_id):
        return self.collection.find_one({"_id": document_id})

    def listing(self, limit, offset):
        items = list(self.collection.find({}).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit))
        return items, self.collection.count_documents({})

    def replace(self, document_id, document, updated_at):
        result = self.collection.update_one(
            {"_id": document_id}, {"$set": {"document": document, "updated_at": updated_at}}
        )
        return result.matched_count == 1

    def delete(self, document_id):
        return self.collection.delete_one({"_id": document_id}).deleted_count == 1


class KafkaLabMessages:
    def __init__(self, bus):
        self.bus = bus

    def publish(self, event):
        reports = []
        producer = self.bus.producer
        producer.produce(
            LAB_TOPIC, key=event["key"],
            value=json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            callback=lambda error, message: reports.append((error, message)),
        )
        # Delivery timeout is also bounded in the existing producer configuration.
        # A timeout/error is UNCERTAIN, not proof that nothing reached the broker.
        producer.flush(12)
        # The producer is shared: flush's remaining count can belong to unrelated
        # task/lab sends. Only THIS record's callback establishes its delivery fact.
        if not reports or reports[0][0] is not None:
            raise ConnectionError("Kafka lab delivery unconfirmed")
        message = reports[0][1]
        partition, offset = message.partition(), message.offset()
        if partition < 0 or offset < 0:
            raise ConnectionError("Kafka lab delivery metadata unavailable")
        return partition, offset


class MemoryLabKV:
    """Explicit test/demo substitute; not evidence of real Redis TTL behavior."""

    def __init__(self, clock=time.monotonic):
        self.values = {}
        self.clock = clock
        self.lock = threading.Lock()

    def snapshot(self, key, value=None, ttl_seconds=None):
        with self.lock:
            instant = self.clock()
            if ttl_seconds is not None:
                self.values[key] = value, instant + ttl_seconds
            current = self.values.get(key)
            if current is None or current[1] <= instant:
                self.values.pop(key, None)
                return None, -2
            return current[0], max(0, int((current[1] - instant) * 1000))

    def delete(self, key):
        with self.lock:
            self.values.pop(key, None)


class MemoryLabDocuments:
    """Explicit test/demo substitute with copy-on-write/read boundaries."""

    def __init__(self):
        self.documents = {}
        self.lock = threading.Lock()

    def create(self, row):
        with self.lock:
            self.documents[row["_id"]] = copy.deepcopy(row)

    def get(self, document_id):
        with self.lock:
            return copy.deepcopy(self.documents.get(document_id))

    def listing(self, limit, offset):
        with self.lock:
            rows = sorted(self.documents.values(), key=lambda row: (row["created_at"], row["_id"]), reverse=True)
            return copy.deepcopy(rows[offset:offset + limit]), len(rows)

    def replace(self, document_id, document, updated_at):
        with self.lock:
            row = self.documents.get(document_id)
            if row is None:
                return False
            row.update(document=copy.deepcopy(document), updated_at=updated_at)
            return True

    def delete(self, document_id):
        with self.lock:
            return self.documents.pop(document_id, None) is not None


class MemoryLabMessages:
    """Explicit test/demo producer only; publishing NEVER fabricates a receipt."""

    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def publish(self, event):
        with self.lock:
            self.messages.append(copy.deepcopy(event))
            return 0, len(self.messages) - 1
