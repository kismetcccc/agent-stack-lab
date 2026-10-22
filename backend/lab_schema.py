"""Fixed, bounded playground DTOs; these are data, never query/command syntax."""

import json
import math
from typing import Annotated, Any, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

LAB_TOPIC = "agent.lab.messages.v1"
LAB_GROUP = "agent-lab-observer-v1"
LAB_REDIS_PREFIX = "lab:kv:"
LAB_KAFKA_ENVELOPE_BYTES = 32768
KEY_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
Key = Annotated[StrictStr, Field(pattern=KEY_PATTERN)]


def utf8(value: str, maximum: int | None = None):
    encoded = value.encode("utf-8")  # Reject unpaired JSON Unicode surrogates before any store call.
    if maximum is not None and len(encoded) > maximum:
        raise ValueError("UTF-8 byte limit exceeded")
    return value


class LabInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordInput(LabInput):
    name: StrictStr = Field(min_length=1, max_length=80)
    value: StrictStr = Field(max_length=1000)

    @field_validator("name", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", "value")
    @classmethod
    def valid_unicode(cls, value):
        return utf8(value)


class RedisInput(LabInput):
    value: StrictStr = Field(max_length=4096)
    ttl_seconds: StrictInt = Field(ge=1, le=3600)

    @field_validator("value")
    @classmethod
    def bounded_value(cls, value):
        return utf8(value, 4096)


class DocumentInput(LabInput):
    document: dict[str, Any]

    @field_validator("document")
    @classmethod
    def bounded_json(cls, document):
        # Iterative checks enforce budgets before calling a recursive JSON/BSON encoder.
        stack = [(document, 1)]
        nodes = 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if nodes > 200:
                raise ValueError("JSON node limit exceeded")
            if isinstance(value, (dict, list)):
                if depth > 6:
                    raise ValueError("JSON container depth exceeded")
                if isinstance(value, dict):
                    for key in value:
                        if not isinstance(key, str) or key.startswith("$") or "." in key or "\0" in key:
                            raise ValueError("unsupported JSON key")
                    values = value.values()
                else:
                    values = value
                stack.extend((child, depth + 1) for child in values)
            elif type(value) is int:
                if not -(2**63) <= value < 2**63:
                    raise ValueError("integer exceeds BSON int64")
            elif type(value) is float:
                if not math.isfinite(value):
                    raise ValueError("non-finite number")
            elif value is not None and not isinstance(value, (str, bool)):
                raise ValueError("JSON values only")
        encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        utf8(encoded, 16384)
        return document


class KafkaInput(LabInput):
    id: UUID4
    key: Key
    value: StrictStr = Field(min_length=1, max_length=4096)

    @field_validator("value")
    @classmethod
    def bounded_value(cls, value):
        return utf8(value, 4096)


class RecordView(BaseModel):
    id: str
    name: str
    value: str
    created_at: str
    updated_at: str


class DocumentView(BaseModel):
    id: str
    document: dict[str, Any]
    created_at: str
    updated_at: str


class RedisView(BaseModel):
    key: str
    exists: bool
    value: str | None
    ttl_ms: int
    observed_at: str


class ProducerView(BaseModel):
    status: Literal["unconfirmed", "acknowledged"]
    acknowledged_at: str | None
    partition: int | None
    offset: int | None


class ConsumerView(BaseModel):
    status: Literal["not_observed", "received"]
    received_at: str | None
    group: Literal["agent-lab-observer-v1"]
    partition: int | None
    offset: int | None
    key: str | None
    value: str | None


class KafkaView(BaseModel):
    id: str
    topic: Literal["agent.lab.messages.v1"]
    key: str
    value: str
    created_at: str
    observed_at: str
    producer: ProducerView
    consumer: ConsumerView


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
