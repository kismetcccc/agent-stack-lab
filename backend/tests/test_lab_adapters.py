"""Fixed adapter call shape tests using doubles, not component integration tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.lab_adapters import REDIS_READ, REDIS_WRITE, MongoLabDocuments, RedisLabKV


def test_redis_uses_only_fixed_atomic_scripts_and_dedicated_namespace():
    client = Mock()
    client.eval.side_effect = [[b"actual persisted", 1450], [b"", 999], [None, -2], [b"external", -1]]
    adapter = RedisLabKV(client)
    assert adapter.snapshot("lesson", "requested", 2) == ("actual persisted", 1450)
    assert client.eval.call_args.args == (REDIS_WRITE, 1, "lab:kv:lesson", "requested", 2000)
    assert adapter.snapshot("lesson") == ("", 999)
    assert client.eval.call_args.args == (REDIS_READ, 1, "lab:kv:lesson")
    assert adapter.snapshot("missing") == (None, -2)
    assert adapter.snapshot("without_ttl") == ("external", -1)
    adapter.delete("lesson")
    client.delete.assert_called_once_with("lab:kv:lesson")
    assert "KEYS" not in [call[0] for call in client.method_calls]


@pytest.mark.parametrize("operation", ["read", "write", "delete"])
def test_redis_connection_errors_propagate_instead_of_cache_style_swallow(operation):
    client = Mock()
    client.eval.side_effect = ConnectionError("offline")
    client.delete.side_effect = ConnectionError("offline")
    adapter = RedisLabKV(client)
    with pytest.raises(ConnectionError):
        if operation == "read":
            adapter.snapshot("key")
        elif operation == "write":
            adapter.snapshot("key", "value", 1)
        else:
            adapter.delete("key")


def test_mongo_queries_are_fixed_collection_and_id_only_not_user_filters():
    collection = Mock()
    client = SimpleNamespace(agent_lab=SimpleNamespace(lab_documents=collection))
    adapter = MongoLabDocuments(client)
    row = {"_id": "server-id", "document": {"_id": "user-data", "value": "<script>text</script>"},
           "created_at": 100.0, "updated_at": 100.0}
    adapter.create(row)
    collection.insert_one.assert_called_once_with(row)
    collection.find_one.return_value = row
    assert adapter.get("server-id") == row
    collection.find_one.assert_called_once_with({"_id": "server-id"})
    collection.update_one.return_value = SimpleNamespace(matched_count=1)
    assert adapter.replace("server-id", {"replacement": True}, 101.0)
    collection.update_one.assert_called_once_with(
        {"_id": "server-id"}, {"$set": {"document": {"replacement": True}, "updated_at": 101.0}},
    )
    collection.delete_one.return_value = SimpleNamespace(deleted_count=0)
    assert adapter.delete("server-id") is False
    collection.delete_one.assert_called_once_with({"_id": "server-id"})
    collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([row])
    collection.count_documents.return_value = 7
    assert adapter.listing(2, 4) == ([row], 7)
    collection.find.assert_called_once_with({})
    collection.find.return_value.sort.assert_called_once_with([("created_at", -1), ("_id", -1)])
    collection.find.return_value.sort.return_value.skip.assert_called_once_with(4)
    collection.count_documents.assert_called_once_with({})
