"""Pure, bounded tools over the current task input; no I/O or side effects."""

import json
import re
import unicodedata
from decimal import Decimal, localcontext

from backend.agent_errors import AgentToolError

RESULT_BYTES = 4096
ARGUMENT_BYTES = 2048


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _schema(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "read_text",
        "Read only task_input, using character offsets.",
        {
            "offset": {"type": "integer", "minimum": 0},
            "length": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
        ["offset", "length"],
    ),
    _schema(
        "search_text",
        "Literal search of task_input; resume from next_offset.",
        {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            "offset": {"type": "integer", "minimum": 0},
        },
        ["query", "limit"],
    ),
    _schema(
        "numeric_stats",
        "Lexical ASCII decimal statistics, not financial parsing. Decimal outputs are strings. "
        "Use spaces or 、 separators, not commas. Exponents, currency and expressions are unsupported.",
        {
            "start": {"type": "integer", "minimum": 0},
            "end": {"type": "integer", "minimum": 1},
        },
        ["start", "end"],
    ),
]


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise AgentToolError("invalid_tool_arguments")
    return value


def _read(arguments, text):
    offset = _integer(arguments["offset"], 0, len(text))
    length = _integer(arguments["length"], 1, 2000)

    def result(size):
        end = offset + size
        return {
            "source": "task_input",
            "offset": offset,
            "text": text[offset:end],
            "next_offset": end,
            "truncated": end < len(text),
        }

    low, high = 0, min(length, len(text) - offset)
    while low < high:
        mid = (low + high + 1) // 2
        if len(json_bytes(result(mid))) <= RESULT_BYTES:
            low = mid
        else:
            high = mid - 1
    return result(low)


def _search(arguments, text):
    query = arguments["query"]
    if type(query) is not str or not 1 <= len(query) <= 200:
        raise AgentToolError("invalid_tool_arguments")
    limit = _integer(arguments["limit"], 1, 5)
    offset = _integer(arguments.get("offset", 0), 0, len(text))
    result = {"source": "task_input", "matches": [], "next_offset": len(text), "truncated": False}
    position = text.find(query, offset)
    while position != -1:
        start, end = max(0, position - 40), min(len(text), position + len(query) + 40)
        hit = {
            "position": position,
            "end": position + len(query),
            "snippet_offset": start,
            "snippet": text[start:end],
        }
        # Reserve the largest possible pagination metadata before admitting a hit.
        candidate = {
            **result,
            "matches": [*result["matches"], hit],
            "next_offset": len(text),
            "truncated": False,
        }
        if len(result["matches"]) >= limit or len(json_bytes(candidate)) > RESULT_BYTES:
            result.update(next_offset=position, truncated=True)
            break
        result["matches"].append(hit)
        position = text.find(query, position + 1)
    return result


_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?", re.ASCII)
_CANDIDATE = re.compile(r"[A-Za-z_0-9.+*/%^=\-]+", re.ASCII)


def _stats(arguments, text):
    start = _integer(arguments["start"], 0, len(text) - 1)
    end = _integer(arguments["end"], start + 1, len(text))
    selected = text[start:end]
    if re.search(r"(?i)(?<![a-z_])(?:nan|infinity)(?![a-z_])", selected):
        raise AgentToolError("unsupported_numeric_format")
    if re.search(r"[0-9][,，][0-9]", selected):
        raise AgentToolError("unsupported_numeric_format")
    for index, char in enumerate(selected):
        if unicodedata.category(char) == "Sc":
            before = selected[index - 1 : index] if index else ""
            after = selected[index + 1 : index + 2]
            if (before and before in "0123456789") or (after and after in "0123456789+-"):
                raise AgentToolError("unsupported_numeric_format")
    numbers = []
    for match in _CANDIDATE.finditer(selected):
        token = match.group()
        if not re.search(r"[0-9]", token):
            continue
        if not _DECIMAL.fullmatch(token):
            raise AgentToolError("unsupported_numeric_format")
        if len(token) > 32 or len(numbers) >= 200:
            raise AgentToolError("numeric_limit_exceeded")
        value = Decimal(token)
        if value.copy_abs() > Decimal("1000000000000"):
            raise AgentToolError("numeric_limit_exceeded")
        numbers.append(value)
    result = {"count": len(numbers), "sum": None, "min": None, "max": None, "mean": None}
    if numbers:
        with localcontext() as context:
            context.prec = 64
            total = sum(numbers, Decimal(0))

            def fixed(value):
                if not value:
                    return "0"
                return format(value.normalize(), "f")

            result.update(
                sum=fixed(total),
                min=fixed(min(numbers)),
                max=fixed(max(numbers)),
                mean=fixed(total / len(numbers)),
            )
    return result


def execute_tool(name, arguments, text):
    """Validate the complete action before executing a pure tool."""
    specs = {
        "read_text": ({"offset", "length"}, set(), _read),
        "search_text": ({"query", "limit"}, {"offset"}, _search),
        "numeric_stats": ({"start", "end"}, set(), _stats),
    }
    if type(name) is not str or name not in specs or type(arguments) is not dict:
        raise AgentToolError("invalid_tool_arguments")
    required, optional, run = specs[name]
    if not required <= arguments.keys() or arguments.keys() - required - optional:
        raise AgentToolError("invalid_tool_arguments")
    try:
        if len(json_bytes(arguments)) > ARGUMENT_BYTES:
            raise AgentToolError("tool_arguments_too_large")
        result = run(arguments, text)
        if len(json_bytes(result)) > RESULT_BYTES:
            raise AgentToolError("tool_result_too_large")
        return result
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        raise AgentToolError("invalid_tool_arguments") from exc
