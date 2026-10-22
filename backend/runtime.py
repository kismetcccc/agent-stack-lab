from backend.adapters import KafkaBus, MemoryBus, MemoryDocuments, Model, MongoDocuments, ProgressCache
from backend.config import Settings
from backend.db import connect
from backend.lab_adapters import (
    KafkaLabMessages,
    MemoryLabDocuments,
    MemoryLabKV,
    MemoryLabMessages,
    MongoLabDocuments,
    RedisLabKV,
)
from backend.lab_service import PlaygroundService
from backend.service import TaskService


class Runtime:
    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.engine, self.sessions = connect(self.settings.database_url)
        lightweight = self.settings.mode in {"test", "demo"}
        self.documents = MemoryDocuments() if lightweight else MongoDocuments(self.settings.mongo_url)
        self.bus = MemoryBus() if lightweight else KafkaBus(self.settings.kafka_servers)
        self.model = Model(self.settings)
        self.cache = ProgressCache(self.settings.redis_url)
        self.tasks = TaskService(
            self.sessions, self.settings, self.documents, self.bus, self.model, self.cache
        )
        self.lab = PlaygroundService(
            self.sessions,
            MemoryLabDocuments() if lightweight else MongoLabDocuments(self.documents.client),
            MemoryLabKV() if lightweight else RedisLabKV(self.cache.client),
            MemoryLabMessages() if lightweight else KafkaLabMessages(self.bus),
        )
