"""Authenticated shared-local lab routes; no task or model prerequisites."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from pydantic import UUID4

from backend.lab_schema import (
    KEY_PATTERN,
    DocumentInput,
    DocumentView,
    KafkaInput,
    KafkaView,
    Page,
    RecordInput,
    RecordView,
    RedisInput,
    RedisView,
)
from backend.service import ServiceError

Limit = Annotated[int, Query(ge=1, le=50)]
Offset = Annotated[int, Query(ge=0, le=10000)]
KeyPath = Annotated[str, Path(pattern=KEY_PATTERN)]


def lab_router(runtime, auth):
    router = APIRouter(prefix="/api/v1/lab", tags=["shared-local-playground"])
    lab = runtime.lab

    def confirm_delete(confirm):
        if not confirm:
            raise ServiceError(422, "confirmation_required", "请明确确认删除这条共享教学数据")

    @router.post("/mysql/records", status_code=201, response_model=RecordView)
    def mysql_create(body: RecordInput, request: Request):
        auth.identity(request, write=True)
        return lab.mysql_create(body.name, body.value)

    @router.get("/mysql/records", response_model=Page[RecordView])
    def mysql_list(request: Request, limit: Limit = 20, offset: Offset = 0):
        auth.identity(request)
        return lab.mysql_list(limit, offset)

    @router.get("/mysql/records/{record_id}", response_model=RecordView)
    def mysql_get(record_id: UUID4, request: Request):
        auth.identity(request)
        return lab.mysql_get(str(record_id))

    @router.put("/mysql/records/{record_id}", response_model=RecordView)
    def mysql_replace(record_id: UUID4, body: RecordInput, request: Request):
        auth.identity(request, write=True)
        return lab.mysql_replace(str(record_id), body.name, body.value)

    @router.delete("/mysql/records/{record_id}", status_code=204)
    def mysql_delete(record_id: UUID4, request: Request, confirm: bool = False):
        auth.identity(request, write=True)
        confirm_delete(confirm)
        lab.mysql_delete(str(record_id))
        return Response(status_code=204)

    @router.put("/redis/keys/{key}", response_model=RedisView)
    def redis_put(key: KeyPath, body: RedisInput, request: Request):
        auth.identity(request, write=True)
        return lab.redis_snapshot(key, body.value, body.ttl_seconds)

    @router.get("/redis/keys/{key}", response_model=RedisView)
    def redis_get(key: KeyPath, request: Request):
        auth.identity(request)
        return lab.redis_snapshot(key)

    @router.delete("/redis/keys/{key}", status_code=204)
    def redis_delete(key: KeyPath, request: Request, confirm: bool = False):
        auth.identity(request, write=True)
        confirm_delete(confirm)
        lab.redis_delete(key)
        return Response(status_code=204)

    @router.post("/mongo/documents", status_code=201, response_model=DocumentView)
    def mongo_create(body: DocumentInput, request: Request):
        auth.identity(request, write=True)
        return lab.mongo_create(body.document)

    @router.get("/mongo/documents", response_model=Page[DocumentView])
    def mongo_list(request: Request, limit: Limit = 20, offset: Offset = 0):
        auth.identity(request)
        return lab.mongo_list(limit, offset)

    @router.get("/mongo/documents/{document_id}", response_model=DocumentView)
    def mongo_get(document_id: UUID4, request: Request):
        auth.identity(request)
        return lab.mongo_get(str(document_id))

    @router.put("/mongo/documents/{document_id}", response_model=DocumentView)
    def mongo_replace(document_id: UUID4, body: DocumentInput, request: Request):
        auth.identity(request, write=True)
        return lab.mongo_replace(str(document_id), body.document)

    @router.delete("/mongo/documents/{document_id}", status_code=204)
    def mongo_delete(document_id: UUID4, request: Request, confirm: bool = False):
        auth.identity(request, write=True)
        confirm_delete(confirm)
        lab.mongo_delete(str(document_id))
        return Response(status_code=204)

    @router.post("/kafka/messages", status_code=202, response_model=KafkaView)
    def kafka_send(body: KafkaInput, request: Request, response: Response):
        auth.identity(request, write=True)
        snapshot, created = lab.kafka_send(str(body.id), body.key, body.value)
        response.status_code = 202 if created else 200
        return snapshot

    @router.get("/kafka/messages", response_model=Page[KafkaView])
    def kafka_list(request: Request, limit: Limit = 20, offset: Offset = 0):
        auth.identity(request)
        return lab.kafka_list(limit, offset)

    @router.get("/kafka/messages/{message_id}", response_model=KafkaView)
    def kafka_get(message_id: UUID4, request: Request):
        auth.identity(request)
        return lab.kafka_get(str(message_id))

    return router
