"""Offline UNIT checks of the HTTP example; mock openers are NOT Compose evidence."""

import copy
import importlib.util
import io
import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/test-http-smoke.py"
SPEC = importlib.util.spec_from_file_location("http_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
TASK_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
TASK_PATH = f"/api/v1/tasks/{TASK_ID}"
SECRET = "SYNTHETIC-PRIVATE-DO-NOT-LOG"


class Response(io.BytesIO):
    def __init__(self, payload=None, status=200, *, raw=None):
        super().__init__(json.dumps(payload).encode() if raw is None else raw)
        self.status = status
        self.read_sizes = []

    def getcode(self):
        return self.status

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Scenario:
    """Small in-memory HTTP double: no backend, server, sockets or provider."""

    def __init__(self):
        self.calls = []
        self.overrides = {}
        self.ready = {"status": "ready", "mode": "production", "model_mode": "deterministic",
                      "dependencies": {"mysql": "up", "mongo": "up", "kafka": "up"}}
        self.task = {"id": TASK_ID, "prompt": smoke.PROMPT, "model_mode": "deterministic",
                     "status": "succeeded", "result_available": True, "attempt_count": 1, "trace_id": "trace"}
        self.result = {"task_id": TASK_ID, "content": "synthetic committed final",
                       "model_mode": "deterministic", "execution_kind": "single_agent",
                       "controller_mode": "scripted_test", "cache_status": "miss"}
        self.attempts = {"items": [{"id": "attempt", "fence": 1, "started_at": "time",
                                    "finished_at": "time", "outcome": "succeeded"}]}
        self.events = {"items": [{"task_id": TASK_ID, "trace_id": "trace", "kind": kind, "component": component}
                                 for kind, component in [("pending", "api"), ("ready", "consumer"),
                                                         ("running", "executor"), ("succeeded", "executor"),
                                                         ("outbox_sent", "relay")]]}
        self.actions = {"availability": "committed", "execution_kind": "single_agent",
                        "controller_mode": "scripted_test", "items": []}
        for tool in ("read_text", "search_text", "numeric_stats"):
            self.actions["items"].extend([
                {"kind": "tool_call", "tool_name": tool, "arguments": {"synthetic": True}},
                {"kind": "tool_result", "tool_name": tool, "arguments": {"synthetic": True},
                 "result": {"synthetic": True}, "truncated": False},
            ])
        self.actions["items"].append({"kind": "final", "content": self.result["content"]})
        for sequence, item in enumerate(self.actions["items"], 1):
            item.update(id=f"attempt:{sequence}", sequence=sequence, task_id=TASK_ID, attempt_id="attempt",
                        execution_kind="single_agent", controller_mode="scripted_test")
        self.task_statuses = []
        self.replay_id = TASK_ID
        self.replay_status = 202
        self.submissions = 0
        self.events_delay = 0
        self.session = False
        self.username = ""
        self.csrf = ""

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        path = urllib.parse.urlsplit(request.full_url).path
        method = request.get_method()
        if path in self.overrides:
            response = self.overrides[path]
            return response(request) if callable(response) else response
        if path == "/healthz":
            return Response({"status": "ok"})
        if path == "/readyz":
            return Response(self.ready)
        if path in {"/api/v1/auth/register", "/api/v1/auth/login"}:
            credentials = json.loads(request.data)
            self.username = credentials["username"]
            self.session = True
            self.csrf = "register-" + SECRET if path.endswith("register") else "login-" + SECRET
            return Response(self.auth(), 201 if path.endswith("register") else 200)
        if path == "/api/v1/auth/me":
            assert self.session
            self.csrf = "refreshed-" + SECRET
            return Response(self.auth())
        if method == "POST":
            assert self.session and request.get_header("X-csrf-token") == self.csrf
        if path == "/api/v1/auth/logout":
            self.session = False
            return Response(status=204, raw=b"")
        if not self.session:
            # Exercise urllib's real non-2xx exception route without a socket.
            raise urllib.error.HTTPError(request.full_url, 401, SECRET, {}, io.BytesIO(SECRET.encode()))
        if path == "/api/v1/tasks":
            self.submissions += 1
            task = {**self.task, "status": "pending", "result_available": False}
            if self.submissions == 2:
                task["id"] = self.replay_id
            return Response(task, self.replay_status if self.submissions == 2 else 202)
        if path == TASK_PATH:
            task = copy.deepcopy(self.task)
            if self.task_statuses:
                task["status"] = self.task_statuses.pop(0)
            return Response(task)
        if path == TASK_PATH + "/results":
            return Response(self.result)
        if path == TASK_PATH + "/attempts":
            return Response(self.attempts)
        if path == TASK_PATH + "/events":
            if self.events_delay:
                self.events_delay -= 1
                return Response({"items": self.events["items"][:-1]})
            return Response(self.events)
        if path == TASK_PATH + "/agent-steps":
            return Response(self.actions)
        raise AssertionError("Unexpected synthetic route")

    def auth(self):
        return {"user": {"id": "owner", "username": self.username}, "csrf_token": self.csrf}


@pytest.fixture
def scenario():
    return Scenario()


@pytest.fixture
def clock():
    return Clock()


def client(scenario, clock, **kwargs):
    return smoke.HttpClient("http://unit.invalid", opener=scenario, clock=clock.monotonic,
                            sleep=clock.sleep, **kwargs)


def test_import_has_no_network_environment_or_random_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("import must not initialize or execute the smoke")

    monkeypatch.setattr(urllib.request, "build_opener", forbidden)
    monkeypatch.setattr(smoke.os, "getenv", forbidden)
    monkeypatch.setattr(smoke.uuid, "uuid4", forbidden)
    spec = importlib.util.spec_from_file_location("import_only_http_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main) and callable(module.run_smoke)


@pytest.mark.parametrize("base", [
    "http://user:password@localhost:8080", "https://localhost?token=private", "https://localhost#private",
    "http://localhost?", "http://localhost#", "file:///tmp/input", "http://localhost/path",
    "http://localhost\\@elsewhere", "http://local\nhost", "http://localhost:bad", "http://localhost:0",
    "http://localhost:65536", "http://%75ser%40localhost", "http://", "", "http://[broken",
])
def test_unsafe_url_is_refused_before_transport(base, scenario, clock):
    with pytest.raises(smoke.SmokeFailure, match="^unsafe_base_url$"):
        smoke.HttpClient(base, opener=scenario, clock=clock.monotonic)
    assert not scenario.calls


@pytest.mark.parametrize("base", [smoke.DEFAULT_BASE_URL, "http://localhost:8080/", "https://example.invalid",
                                  "http://[::1]:8080"])
def test_explicit_origin_and_default_localhost_are_accepted(base):
    assert smoke.validate_base_url(base) == base.rstrip("/")


def test_standard_opener_disables_redirects_and_preserves_tls_verification():
    opener = smoke.build_opener()
    assert any(isinstance(handler, smoke.NoRedirect) for handler in opener.handlers)
    assert any(isinstance(handler, urllib.request.HTTPCookieProcessor) for handler in opener.handlers)
    https = next(handler for handler in opener.handlers if isinstance(handler, urllib.request.HTTPSHandler))
    assert https._context.verify_mode == ssl.CERT_REQUIRED and https._context.check_hostname


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_handler_refuses_redirect_target(status):
    with pytest.raises(smoke.SmokeFailure, match="^redirect_refused$"):
        smoke.NoRedirect().redirect_request(
            urllib.request.Request("http://unit.invalid"), None, status, SECRET, {}, "https://private.invalid/"
        )


@pytest.mark.parametrize("changes", [
    {"mode": "test"}, {"mode": "demo"}, {"model_mode": "live"}, {"model_mode": None},
    {"status": "not_ready"}, {"dependencies": {}}, {"dependencies": None},
    {"dependencies": {"mysql": "up", "mongo": "in_memory_test_adapter", "kafka": "up"}},
    {"dependencies": {"mysql": "down", "mongo": "up", "kafka": "up"}},
    {"dependencies": {"mysql": "up", "mongo": "up", "kafka": "down"}},
    {"dependencies": {"mysql": "up", "mongo": "up", "kafka": "up", "sqlite": "up"}},
])
def test_readiness_refuses_wrong_mode_or_dependency_before_any_post(changes, scenario, clock):
    scenario.ready.update(changes)
    with pytest.raises(smoke.SmokeFailure):
        smoke.run_smoke(client(scenario, clock))
    assert [request.get_method() for request, _ in scenario.calls] == ["GET", "GET"]


def test_complete_cycle_uses_latest_csrf_and_same_key_prompt_and_accepts_async_timing(scenario, clock, capsys):
    scenario.task_statuses = ["pending", "ready", "running", "retry_wait", "running"]
    scenario.events_delay = 2
    smoke.run_smoke(client(scenario, clock))
    assert capsys.readouterr() == ("", "")  # Only main prints a fully verified success.
    assert not scenario.session and clock.now == 7
    posts = [request for request, _ in scenario.calls if request.get_method() == "POST"]
    tasks = [request for request in posts if request.full_url.endswith("/tasks")]
    assert len(tasks) == 2 and tasks[0].data == tasks[1].data
    assert tasks[0].get_header("Idempotency-key") == tasks[1].get_header("Idempotency-key")
    assert all(request.get_header("X-csrf-token") == "refreshed-" + SECRET for request in tasks + posts[-1:])
    assert posts[1].get_header("X-csrf-token") == "register-" + SECRET
    assert scenario.calls[-1][0].full_url.endswith(TASK_PATH)
    assert all(0 < timeout <= smoke.REQUEST_SECONDS for _, timeout in scenario.calls)


def test_replay_id_mismatch_is_not_success(scenario, clock):
    scenario.replay_id = OTHER_ID
    with pytest.raises(smoke.SmokeFailure, match="idempotency_or_task_mismatch"):
        smoke.run_smoke(client(scenario, clock))


def test_identical_replay_must_not_return_idempotency_conflict(scenario, clock):
    scenario.replay_status = 409
    with pytest.raises(smoke.SmokeFailure, match="^http_status_409$"):
        smoke.run_smoke(client(scenario, clock))


@pytest.mark.parametrize("state", ["failed", "unrecognized"])
def test_task_failure_or_invalid_status_does_not_report_raw_error(state, scenario, clock):
    scenario.task_statuses = [state]
    scenario.task["error"] = {"message": SECRET}
    with pytest.raises(smoke.SmokeFailure) as error:
        smoke.run_smoke(client(scenario, clock))
    assert SECRET not in str(error.value)


def test_task_poll_has_total_deadline(scenario, clock):
    scenario.task_statuses = ["pending"] * 20
    with pytest.raises(smoke.SmokeFailure, match="deadline_exceeded"):
        smoke.run_smoke(client(scenario, clock, total_seconds=3))
    assert clock.now == 3


def test_late_relay_event_wait_is_also_deadline_bounded(scenario, clock):
    scenario.events_delay = 20
    with pytest.raises(smoke.SmokeFailure, match="deadline_exceeded"):
        smoke.run_smoke(client(scenario, clock, total_seconds=2))
    assert clock.now == 2


@pytest.mark.parametrize("status, raw, label", [
    (200, b"", "malformed_response"), (200, b"not-json-" + SECRET.encode(), "malformed_response"),
    (200, b"\xff", "malformed_response"), (200, b"[]", "malformed_response"),
    (204, b"{}", "unexpected_response_body"), (302, b"", "http_status_302"),
    (503, SECRET.encode(), "http_status_503"),
])
def test_malformed_body_and_status_failures_are_fixed_labels(status, raw, label, scenario, clock):
    scenario.overrides["/unit"] = Response(status=status, raw=raw)
    with pytest.raises(smoke.SmokeFailure, match=f"^{label}$"):
        client(scenario, clock).request("GET", "/unit", status=204 if status == 204 else 200)


def test_empty_204_is_accepted_without_json_parse(scenario, clock):
    scenario.overrides["/unit"] = Response(status=204, raw=b"")
    assert client(scenario, clock).request("POST", "/unit", status=204) is None


def test_oversized_body_is_read_with_size_cap_then_closed(scenario, clock):
    response = Response(raw=b"x" * 100)
    scenario.overrides["/unit"] = response
    with pytest.raises(smoke.SmokeFailure, match="response_too_large"):
        client(scenario, clock, max_response_bytes=32).request("GET", "/unit")
    assert response.read_sizes == [33] and response.closed


def test_transport_exception_is_redacted(scenario, clock):
    def fail(request):
        raise OSError(SECRET)

    scenario.overrides["/unit"] = fail
    with pytest.raises(smoke.SmokeFailure, match="^transport_error$"):
        client(scenario, clock).request("GET", "/unit")


@pytest.mark.parametrize("phase", ["open", "body"])
def test_request_timeout_covers_blocking_open_or_trickling_body(phase):
    release = threading.Event()

    class BlockingResponse(Response):
        def read(self, size=-1):
            release.wait(2)
            return super().read(size)

    class BlockingOpener:
        def open(self, request, timeout):
            if phase == "body":
                return BlockingResponse({"status": "late"})
            release.wait(2)
            return Response({"status": "late"})

    instance = smoke.HttpClient("http://unit.invalid", opener=BlockingOpener(), request_seconds=0.02)
    start = time.monotonic()
    try:
        with pytest.raises(smoke.SmokeFailure, match="request_timeout"):
            instance.request("GET", "/unit")
        assert time.monotonic() - start < 1
    finally:
        release.set()


def test_total_deadline_limits_each_request_and_checks_elapsed_exchange(scenario, clock):
    def slow(request):
        clock.sleep(3)
        return Response({"status": "late"})

    scenario.overrides["/unit"] = slow
    with pytest.raises(smoke.SmokeFailure, match="deadline_exceeded"):
        client(scenario, clock, total_seconds=2).request("GET", "/unit")
    assert scenario.calls[0][1] == 2


@pytest.mark.parametrize("target, changes, label", [
    ("task", {"result_available": False}, "result_not_committed"),
    ("task", {"attempt_count": 2}, "attempt_count_mismatch"),
    ("result", {"model_mode": "live"}, "deterministic_required"),
    ("result", {"controller_mode": "live_llm"}, "agent_mode_mismatch"),
    ("result", {"execution_kind": "legacy_single_call"}, "agent_mode_mismatch"),
    ("result", {"content": ""}, "empty_result"),
    ("result", {"task_id": OTHER_ID}, "result_task_mismatch"),
    ("actions", {"availability": "not_committed"}, "actions_not_committed"),
    ("actions", {"controller_mode": "live_llm"}, "agent_mode_mismatch"),
    ("actions", {"items": []}, "invalid_agent_actions"),
    ("actions", {"items": ["not a step"]}, "invalid_agent_actions"),
    ("attempts", {"items": []}, "no_successful_attempt"),
])
def test_committed_result_and_actions_are_verified(target, changes, label, scenario, clock):
    getattr(scenario, target).update(changes)
    with pytest.raises(smoke.SmokeFailure, match=f"^{label}$"):
        smoke.run_smoke(client(scenario, clock))


@pytest.mark.parametrize("index, changes, label", [
    (0, {"attempt_id": "old-attempt"}, "action_attempt_mismatch"),
    (0, {"sequence": 7}, "invalid_agent_actions"),
    (0, {"tool_name": "shell"}, "invalid_agent_actions"),
    (1, {"result": None}, "invalid_agent_actions"),
    (1, {"truncated": "false"}, "invalid_agent_actions"),
    (2, {"controller_mode": "live_llm"}, "agent_mode_mismatch"),
    (6, {"content": "uncommitted final"}, "final_result_mismatch"),
])
def test_agent_actions_must_match_committed_attempt_and_readonly_loop(index, changes, label, scenario, clock):
    scenario.actions["items"][index].update(changes)
    with pytest.raises(smoke.SmokeFailure, match=f"^{label}$"):
        smoke.run_smoke(client(scenario, clock))


def test_csrf_must_rotate(scenario, clock):
    scenario.overrides["/api/v1/auth/me"] = lambda request: Response(scenario.auth())
    with pytest.raises(smoke.SmokeFailure, match="csrf_not_rotated"):
        smoke.run_smoke(client(scenario, clock))
    assert scenario.submissions == 0


def test_logout_must_reject_protected_read(scenario, clock):
    def detail_even_without_session(request):
        return Response(scenario.task)

    scenario.overrides[TASK_PATH] = detail_even_without_session
    with pytest.raises(smoke.SmokeFailure, match="http_status_200"):
        smoke.run_smoke(client(scenario, clock))


def test_main_reports_only_complete_success_without_credentials(monkeypatch, scenario, clock, capsys):
    instance = client(scenario, clock)
    monkeypatch.setattr(smoke, "HttpClient", lambda _: instance)
    assert smoke.main() == 0
    output = capsys.readouterr()
    assert output.out.strip() == smoke.SUCCESS and not output.err
    all_output = output.out + output.err
    registered = next(request for request, _ in scenario.calls if request.full_url.endswith("/register"))
    credentials = json.loads(registered.data)
    assert SECRET not in all_output
    assert all(value not in all_output for value in credentials.values())


def test_main_refuses_secret_bearing_environment_url_without_echoing_it(monkeypatch, capsys):
    monkeypatch.setenv("TEST_BASE_URL", f"https://user:{SECRET}@unit.invalid")

    def forbidden():
        pytest.fail("unsafe origin must fail before creating the opener")

    monkeypatch.setattr(smoke, "build_opener", forbidden)
    assert smoke.main() == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err == "FAIL: HTTP smoke: unsafe_base_url\n"


@pytest.mark.parametrize("failure", ["status", "unexpected"])
def test_main_failure_has_no_raw_response_secrets_or_traceback(failure, monkeypatch, scenario, clock, capsys):
    if failure == "status":
        scenario.overrides["/readyz"] = Response(status=503, raw=SECRET.encode())
        instance = client(scenario, clock)
        monkeypatch.setattr(smoke, "HttpClient", lambda _: instance)
    else:
        def fail(_):
            raise ValueError(SECRET)

        monkeypatch.setattr(smoke, "HttpClient", fail)
    assert smoke.main() == 1
    output = capsys.readouterr()
    assert not output.out and "FAIL: HTTP smoke:" in output.err
    assert SECRET not in output.err and "Traceback" not in output.err
