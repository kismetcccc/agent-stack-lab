"""Provider protocol tests use local MockTransport only; not live compatibility evidence."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from backend.agent_errors import (
    AgentBudgetError,
    AgentConfigurationError,
    AgentProtocolError,
    AgentRefused,
    ProviderTransientError,
)
from backend.agent_provider import LiveController, decode, normalize
from backend.agent_types import Final, ToolCall


def completion(content="done", *, reason="stop", **message):
    return {
        "choices": [
            {
                "finish_reason": reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                    **message,
                },
            }
        ]
    }


def call(arguments='{"offset":0,"length":10}', **kwargs):
    return {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "read_text",
            "arguments": arguments,
        },
        **kwargs,
    }


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "mock-key-not-a-secret")
    monkeypatch.setenv("MODEL_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("MODEL_NAME", "mock-only")

    def make(handler):
        return LiveController(
            SimpleNamespace(model_mode="live", live_enabled=True), transport=httpx.MockTransport(handler)
        )

    return make


def invoke(instance, prompt="hello", observations=None, seconds=5):
    return asyncio.run(instance.next(prompt, observations or [], time.monotonic() + seconds))


def test_final_and_auxiliary_tool_text():
    assert normalize(completion()) == Final("done")
    decision = normalize(
        completion(
            "ignored auxiliary text", reason="tool_calls", tool_calls=[call()], reasoning="do not persist me"
        )
    )
    assert decision == ToolCall("call-1", "read_text", {"offset": 0, "length": 10})
    assert "ignored" not in repr(decision) and "persist" not in repr(decision)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"choices": []},
        {"choices": [{}, {}]},
        completion(""),
        completion("   "),
        completion(None),
        completion(4),
        completion(reason="length"),
        completion(reason="unknown"),
        completion(reason="tool_calls"),
        completion(tool_calls=[call()]),
        completion(reason="tool_calls", tool_calls=[call(), call()]),
        completion(reason="tool_calls", tool_calls="wrong"),
        completion(reason="tool_calls", tool_calls=[call(id="")]),
        completion(reason="tool_calls", tool_calls=[call(id="x" * 129)]),
        completion(reason="tool_calls", tool_calls=[call(arguments="[]")]),
        completion(reason="tool_calls", tool_calls=[call(arguments="not JSON")]),
        completion(reason="tool_calls", tool_calls=[call(arguments='{"x":1,"x":2}')]),
        completion(reason="tool_calls", tool_calls=[call(arguments='{"x":NaN}')]),
        completion(function_call={"name": "old"}),
        completion("\ud800"),
    ],
)
def test_protocol_rejections(payload):
    with pytest.raises(AgentProtocolError):
        normalize(payload)


def test_refusal_and_byte_budgets():
    with pytest.raises(AgentRefused):
        normalize(completion(refusal="cannot"))
    with pytest.raises(AgentBudgetError):
        normalize(completion("界" * 3000))
    with pytest.raises(AgentBudgetError):
        normalize(completion(reason="tool_calls", tool_calls=[call(arguments=" " * 2049)]))
    with pytest.raises(AgentProtocolError):
        decode('{"choices":[],"choices":[]}')


def test_live_sends_observations_not_reasoning(controller):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    observation = {
        "call_id": "a",
        "tool_name": "read_text",
        "arguments": {"offset": 0, "length": 1},
        "result": {"text": "a"},
        "reasoning": "NEVER SEND",
    }
    assert invoke(controller(handler), observations=[observation]) == Final("done")
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["max_tokens"] == 1024 and body["parallel_tool_calls"] is False
    assert len(body["tools"]) == 3
    assert body["messages"][-1] == {"role": "tool", "tool_call_id": "a", "content": '{"text":"a"}'}
    assert b"NEVER SEND" not in requests[0].content


@pytest.mark.parametrize(
    "status,error",
    [
        (429, ProviderTransientError),
        (500, ProviderTransientError),
        (401, AgentProtocolError),
        (302, AgentProtocolError),
    ],
)
def test_http_errors_without_retry(controller, status, error):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="provider secret must not escape")

    with pytest.raises(error) as caught:
        invoke(controller(handler))
    assert "secret" not in str(caught.value) and len(calls) == 1


def test_request_and_response_caps(controller):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * 65537)

    with pytest.raises(AgentBudgetError):
        invoke(controller(handler), prompt="界" * 30000)
    assert not calls
    with pytest.raises(AgentBudgetError):
        invoke(controller(handler))
    assert len(calls) == 1


def test_transport_timeout_is_transient_until_deadline(controller):
    def handler(request):
        raise httpx.ReadTimeout("private network details", request=request)

    with pytest.raises(ProviderTransientError) as caught:
        invoke(controller(handler))
    assert "private" not in str(caught.value)


def test_deadline_cancels_request_and_no_expired_request(controller):
    state = []

    async def handler(request):
        state.append("started")
        try:
            await asyncio.sleep(1)
        finally:
            state.append("cancelled")
        return httpx.Response(200, json=completion())

    instance = controller(handler)
    with pytest.raises(AgentBudgetError):
        invoke(instance, seconds=-1)
    assert state == []
    with pytest.raises(AgentBudgetError):
        invoke(instance, seconds=0.01)
    assert state == ["started", "cancelled"]


def test_malformed_and_encoded_response(controller):
    with pytest.raises(AgentProtocolError):
        invoke(controller(lambda request: httpx.Response(200, content=b"not json")))
    with pytest.raises(AgentProtocolError):
        invoke(
            controller(
                lambda request: httpx.Response(200, headers={"content-encoding": "custom"}, content=b"x")
            )
        )


@pytest.mark.parametrize(
    "base",
    [
        "http://provider.invalid",
        "https://",
        "https://u:p@provider.invalid",
        "https://provider.invalid?key=secret",
        "https://provider.invalid/#fragment",
        "https://provider.invalid:bad",
    ],
)
def test_invalid_provider_url(controller, monkeypatch, base):
    monkeypatch.setenv("MODEL_BASE_URL", base)
    with pytest.raises(AgentConfigurationError):
        controller(lambda request: pytest.fail("must not call"))


def test_live_requires_explicit_authorization(controller):
    with pytest.raises(AgentConfigurationError):
        LiveController(SimpleNamespace(model_mode="live", live_enabled=False))
    with pytest.raises(AgentConfigurationError):
        LiveController(SimpleNamespace(model_mode="deterministic", live_enabled=True))


def test_oversized_stream_stops_at_first_excess_byte_and_closes(controller):
    state = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b" " * 65536
            state.append("excess")
            yield b"x"
            state.append("should_not_read")
            await asyncio.sleep(1)
            yield b"ignored"

        async def aclose(self):
            state.append("closed")

    with pytest.raises(AgentBudgetError):
        invoke(controller(lambda request: httpx.Response(200, stream=Body())))
    assert state == ["excess", "closed"]


def test_stream_total_deadline_closes_slow_response(controller):
    state = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            try:
                await asyncio.sleep(1)
            finally:
                state.append("cancelled")
            yield b"}"

        async def aclose(self):
            state.append("closed")

    with pytest.raises(AgentBudgetError):
        invoke(controller(lambda request: httpx.Response(200, stream=Body())), seconds=0.01)
    assert state == ["cancelled", "closed"]
