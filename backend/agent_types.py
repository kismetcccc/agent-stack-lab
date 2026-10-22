"""Public decisions, not hidden reasoning."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Final:
    content: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool_name: str
    arguments: dict
