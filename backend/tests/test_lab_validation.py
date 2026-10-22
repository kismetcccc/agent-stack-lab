"""Offline DTO tests, not evidence of real component persistence."""

import json

import pytest
from pydantic import ValidationError

from backend.lab_schema import DocumentInput, KafkaInput, RecordInput, RedisInput

MESSAGE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize("body", [
    {"name": " ", "value": ""}, {"name": "x" * 81, "value": ""},
    {"name": "ok", "value": "x" * 1001}, {"name": 1, "value": "ok"},
    {"name": "ok", "value": False}, {"name": "ok", "value": "", "owner_id": "no"},
    {"name": "\ud800", "value": ""}, {"name": "ok", "value": "\udfff"},
])
def test_record_rejects_invalid_types_lengths_and_untrusted_fields(body):
    with pytest.raises(ValidationError):
        RecordInput.model_validate(body)


def test_record_trim_and_character_not_byte_limits():
    body = RecordInput.model_validate({"name": "  " + "你" * 80 + "  ", "value": "你" * 1000})
    assert body.name == "你" * 80 and body.value == "你" * 1000
    assert RecordInput(name="same name", value="").value == ""


@pytest.mark.parametrize("ttl", [0, -1, 3601, True, False, 1.0, "1", None])
def test_redis_ttl_is_a_bounded_strict_integer(ttl):
    with pytest.raises(ValidationError):
        RedisInput(value="hello", ttl_seconds=ttl)


@pytest.mark.parametrize("value", ["你" * 1366, "x" * 4097, "\ud800", 12, False, None])
def test_redis_value_bound_is_utf8(value):
    with pytest.raises(ValidationError):
        RedisInput(value=value, ttl_seconds=10)


def test_redis_boundary_empty_value_and_exact_utf8_size():
    assert RedisInput(value="", ttl_seconds=1).value == ""
    assert len(RedisInput(value="你" * 1365 + "x", ttl_seconds=3600).value.encode()) == 4096
    with pytest.raises(ValidationError):
        RedisInput(value="ok", ttl_seconds=1, command="FLUSHALL")


@pytest.mark.parametrize("document", [
    [], "text", None, {"$where": "no"}, {"a.b": 1}, {"bad\0key": 1},
    {"nested": [{"$inc": 1}]}, {"nested": {"a.b": 1}},
    {"n": 2**63}, {"n": -(2**63) - 1}, {"n": float("inf")},
    {"n": float("-inf")}, {"n": float("nan")}, {"x": "\ud800"}, {"\udfff": 1},
    {"n": b"not-json"}, {"n": {1, 2}},
])
def test_mongo_invalid_json_is_rejected_before_storage(document):
    with pytest.raises(ValidationError):
        DocumentInput(document=document)


def nested(depth):
    value = {"value": 1}
    for _ in range(depth - 1):
        value = {"child": [value]}  # Adds two containers.
    return value


def test_mongo_container_depth_counts_arrays_not_scalar_leaves():
    value = {"x": 1}
    for _ in range(5):
        value = {"child": value}
    assert DocumentInput(document=value).document == value  # six objects plus scalar
    with pytest.raises(ValidationError):
        DocumentInput(document={"child": value})
    assert DocumentInput(document=nested(3))
    with pytest.raises(ValidationError):
        DocumentInput(document=nested(4))


def test_mongo_node_budget_and_exact_utf8_size():
    assert DocumentInput(document={str(i): None for i in range(199)})
    with pytest.raises(ValidationError):
        DocumentInput(document={str(i): None for i in range(200)})
    # Compact wrapper {"x":""} is 8 bytes; ensure ASCII escaping isn't used for the limit.
    value = {"x": "你" * 5458 + "xx"}
    assert len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) == 16384
    assert DocumentInput(document=value)
    with pytest.raises(ValidationError):
        DocumentInput(document={"x": value["x"] + "x"})


def test_mongo_allowed_json_boundaries_and_wrapper_is_not_query():
    body = {"_id": "just-data", "low": -(2**63), "high": 2**63 - 1, "bool": True,
            "null": None, "nested": ["<script>text</script>", 1.5, {}]}
    assert DocumentInput(document=body).document == body
    with pytest.raises(ValidationError):
        DocumentInput(document={}, collection="results")


@pytest.mark.parametrize("updates", [
    {"id": "bad"}, {"id": "11111111-1111-1111-8111-111111111111"},
    {"key": ""}, {"key": "x" * 65}, {"key": "with.dot"}, {"key": "中文"},
    {"value": ""}, {"value": "你" * 1366}, {"value": "\ud800"},
    {"value": 12}, {"topic": "agent.tasks"}, {"group": "other"},
])
def test_kafka_fixed_small_uuid_key_string_protocol(updates):
    body = {"id": MESSAGE_ID, "key": "ASCII_01-valid", "value": "hello"} | updates
    with pytest.raises(ValidationError):
        KafkaInput.model_validate(body)


def test_kafka_maximum_utf8_value_and_normalized_uuid():
    body = KafkaInput(id=MESSAGE_ID.upper(), key="a" * 64, value="你" * 1365 + "x")
    assert str(body.id) == MESSAGE_ID
    assert len(body.value.encode()) == 4096
