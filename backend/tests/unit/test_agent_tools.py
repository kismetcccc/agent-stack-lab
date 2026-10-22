import json

import pytest

from backend.agent_errors import AgentToolError
from backend.agent_tools import execute_tool, json_bytes


def stats(text):
    return execute_tool("numeric_stats", {"start": 0, "end": len(text)}, text)


def test_decimal_statistics_and_empty():
    assert stats("1、2；3 -0.5") == {"count": 4, "sum": "5.5", "min": "-0.5", "max": "3", "mean": "1.375"}
    assert stats("没有数字") == {"count": 0, "sum": None, "min": None, "max": None, "mean": None}
    assert stats("0.1 0.2")["sum"] == "0.3"
    assert stats("-0 +0.00")["sum"] == "0"


@pytest.mark.parametrize(
    "text",
    [
        "1e6",
        "-2E-3",
        "1,000",
        "1，000",
        "1,2,3",
        "$12",
        "12€",
        "￥-12",
        "NaN",
        "Infinity",
        "abc12",
        "12abc",
        "_12",
        "12_",
        "1+2",
        "1.2.3",
        "-1-2",
        "1/2",
        "1*2",
        ".5",
        "5.",
    ],
)
def test_unsupported_numbers_rejected_whole_call(text):
    with pytest.raises(AgentToolError, match="unsupported_numeric_format"):
        stats("4 " + text + " 5")


@pytest.mark.parametrize(
    "text", ["1000000000001", "1000000000000.00000000000000001", "-1000000000001", "0" * 33, "1 " * 201]
)
def test_numeric_limits(text):
    with pytest.raises(AgentToolError):
        stats(text)


def test_numeric_allowed_boundaries():
    assert stats("1000000000000 -1000000000000")["sum"] == "0"
    assert stats("1 " * 200)["count"] == 200
    assert stats("0." + "0" * 29 + "1")["count"] == 1


@pytest.mark.parametrize(
    "name,args",
    [
        ("shell", {}),
        ("read_text", {"offset": False, "length": 1}),
        ("read_text", {"offset": 0, "length": True}),
        ("read_text", {"offset": 4, "length": 1}),
        ("read_text", {"offset": 0, "length": 2001}),
        ("read_text", {"offset": 0, "length": 1, "path": "/etc"}),
        ("search_text", {"query": "", "limit": 1}),
        ("search_text", {"query": "a", "limit": False}),
        ("search_text", {"query": "a", "limit": 1, "offset": -1}),
        ("numeric_stats", {"start": 0, "end": 0}),
        ("numeric_stats", {"start": 0, "end": 4}),
        ("numeric_stats", {"start": 0, "end": True}),
        ("read_text", {"offset": 0}),
    ],
)
def test_strict_arguments(name, args):
    with pytest.raises(AgentToolError):
        execute_tool(name, args, "abc")


@pytest.mark.parametrize("text", ["😀" * 2000, "\x00" * 2000, '\\"\n' * 1500, "汉字" * 2000])
def test_read_actual_json_budget_and_resume(text):
    offset, fragments = 0, []
    while offset < len(text):
        result = execute_tool("read_text", {"offset": offset, "length": 2000}, text)
        assert len(json_bytes(result)) <= 4096
        assert json.loads(json_bytes(result)) == result
        assert result["next_offset"] == offset + len(result["text"])
        assert result["next_offset"] > offset
        offset = result["next_offset"]
        assert result["truncated"] == (offset < len(text))
        fragments.append(result["text"])
    assert "".join(fragments) == text


def test_read_end_of_input():
    assert execute_tool("read_text", {"offset": 3, "length": 20}, "abc")["text"] == ""


def test_literal_search_and_offset():
    result = execute_tool("search_text", {"query": "a.*", "limit": 1}, "a.* a.*")
    assert result["matches"][0]["position"] == 0
    assert result["next_offset"] == 4
    assert result["truncated"] is True
    result = execute_tool("search_text", {"query": "a.*", "limit": 1, "offset": 4}, "a.* a.*")
    assert result["matches"][0]["position"] == 4
    assert result["next_offset"] == 7
    assert result["truncated"] is False


@pytest.mark.parametrize("query", ["😀" * 200, "\x00" * 200, '\\"' * 100])
def test_search_byte_budget_never_loses_matches(query):
    text = (query + " separator ") * 8
    expected, cursor = [], 0
    while (position := text.find(query, cursor)) != -1:
        expected.append(position)
        cursor = position + 1
    actual, offset = [], 0
    while True:
        result = execute_tool("search_text", {"query": query, "limit": 5, "offset": offset}, text)
        assert len(json_bytes(result)) <= 4096
        assert json.loads(json_bytes(result)) == result
        actual.extend(hit["position"] for hit in result["matches"])
        if not result["truncated"]:
            assert result["next_offset"] == len(text)
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert actual == expected
