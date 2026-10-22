"""Offline hook/probe regressions. These do NOT count as real SIGKILL experiments."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend import faults
from backend.config import Settings
from backend.db import Attempt, Outbox, Task
from backend.migrate import migrate
from backend.runtime import Runtime

TASK = str(uuid4())
RUN = str(uuid4())
EVENT = str(uuid4())
ATTEMPT = str(uuid4())
KEYS = ("LAB_TEST_HOOKS", "LAB_TEST_PAUSE_AT", "LAB_TEST_TASK_ID", "LAB_TEST_RUN_ID")
POINTS = ("after_outbox_publish", "after_inbox_commit", "after_claim", "after_mongo_save")


@pytest.fixture(autouse=True)
def isolated_hooks(monkeypatch, tmp_path):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(faults, "MARKER_DIR", tmp_path)
    sleep = Mock()
    monkeypatch.setattr(faults.time, "sleep", sleep)
    return sleep


def enabled(monkeypatch, point):
    for key, value in zip(KEYS, ("true", point, TASK, RUN), strict=True):
        monkeypatch.setenv(key, value)


def metadata(point):
    if point == "after_outbox_publish":
        return {"event_id": EVENT}
    if point == "after_inbox_commit":
        return {"event_id": EVENT, "topic": "agent.tasks", "partition": 0, "offset": 42}
    return {"attempt_id": ATTEMPT, "fence": 1}


@pytest.mark.parametrize("point", POINTS)
def test_allowed_target_has_safe_live_marker_and_bounded_cleanup(monkeypatch, isolated_hooks, point):
    enabled(monkeypatch, point)

    def inspect(seconds):
        assert seconds == 90
        marker = faults.read_marker(point, TASK, RUN)
        assert set(marker) == {
            "version",
            "point",
            "task_id",
            "run_id",
            "pid",
            "process_start",
            "created_at",
            "expires_at",
        } | set(metadata(point))
        assert marker["pid"] == os.getpid()
        assert {key: marker[key] for key in metadata(point)} == metadata(point)
        assert faults.marker_path(point, RUN).stat().st_mode & 0o777 == 0o600

    isolated_hooks.side_effect = inspect
    faults.pause_at(point, TASK, **metadata(point))
    isolated_hooks.assert_called_once_with(90)
    assert not list(faults.MARKER_DIR.iterdir())


@pytest.mark.parametrize("value", (None, "false", "TRUE", "1", ""))
def test_disabled_hook_does_not_validate_write_or_sleep(monkeypatch, isolated_hooks, value):
    if value is not None:
        monkeypatch.setenv("LAB_TEST_HOOKS", value)
    faults.pause_at("unknown", "not-even-an-id")
    isolated_hooks.assert_not_called()
    assert not list(faults.MARKER_DIR.iterdir())


@pytest.mark.parametrize(
    "key,value",
    (
        ("LAB_TEST_TASK_ID", None),
        ("LAB_TEST_TASK_ID", ""),
        ("LAB_TEST_TASK_ID", str(uuid4())),
        ("LAB_TEST_RUN_ID", None),
        ("LAB_TEST_RUN_ID", "../../unsafe"),
        ("LAB_TEST_PAUSE_AT", "after_mongo_save"),
        ("LAB_TEST_PAUSE_AT", "unknown"),
    ),
)
def test_missing_or_wrong_target_config_never_pauses(monkeypatch, isolated_hooks, key, value):
    enabled(monkeypatch, "after_claim")
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    faults.pause_at("after_claim", TASK, **metadata("after_claim"))
    isolated_hooks.assert_not_called()
    assert not list(faults.MARKER_DIR.iterdir())


@pytest.mark.parametrize("task", (None, "", "../../unsafe", str(uuid4())))
def test_missing_invalid_or_unrelated_task_never_pauses(monkeypatch, isolated_hooks, task):
    enabled(monkeypatch, "after_claim")
    faults.pause_at("after_claim", task, **metadata("after_claim"))
    isolated_hooks.assert_not_called()
    assert not list(faults.MARKER_DIR.iterdir())


def test_unknown_enabled_hook_fails_closed(monkeypatch, isolated_hooks):
    enabled(monkeypatch, "unknown")
    with pytest.raises(ValueError, match="unknown fault point"):
        faults.pause_at("unknown", TASK)
    isolated_hooks.assert_not_called()


@pytest.mark.parametrize(
    "point,invalid",
    (
        ("after_outbox_publish", {"event_id": "private prompt"}),
        ("after_claim", {"attempt_id": ATTEMPT, "fence": True}),
        ("after_mongo_save", {"attempt_id": None, "fence": 1}),
        ("after_inbox_commit", {"event_id": EVENT, "topic": "private prompt", "partition": 0, "offset": 1}),
        ("after_inbox_commit", {"event_id": EVENT, "topic": "topic", "partition": -1, "offset": 1}),
        ("after_inbox_commit", {"event_id": EVENT, "topic": "topic", "partition": 0, "offset": None}),
    ),
)
def test_invalid_metadata_cannot_create_marker(monkeypatch, isolated_hooks, point, invalid):
    enabled(monkeypatch, point)
    with pytest.raises(ValueError):
        faults.pause_at(point, TASK, **invalid)
    isolated_hooks.assert_not_called()
    assert not list(faults.MARKER_DIR.iterdir())


def test_marker_cleanup_even_when_sleep_is_interrupted(monkeypatch, isolated_hooks):
    enabled(monkeypatch, "after_claim")
    isolated_hooks.side_effect = InterruptedError
    with pytest.raises(InterruptedError):
        faults.pause_at("after_claim", TASK, **metadata("after_claim"))
    assert not list(faults.MARKER_DIR.iterdir())


@pytest.mark.parametrize("stale", ("expired", "other_task", "other_process", "other_run"))
def test_stale_marker_is_rejected(monkeypatch, isolated_hooks, stale):
    enabled(monkeypatch, "after_claim")

    def inspect(_):
        path = faults.marker_path("after_claim", RUN)
        marker = json.loads(path.read_text())
        if stale == "expired":
            marker["created_at"] -= 100
            marker["expires_at"] -= 100
        elif stale == "other_task":
            marker["task_id"] = str(uuid4())
        elif stale == "other_run":
            marker["run_id"] = str(uuid4())
        else:
            marker["process_start"] = "not-this-process"
        path.write_text(json.dumps(marker))
        with pytest.raises(ValueError, match="stale or mismatched"):
            faults.read_marker("after_claim", TASK, RUN)

    isolated_hooks.side_effect = inspect
    faults.pause_at("after_claim", TASK, **metadata("after_claim"))
    assert not list(faults.MARKER_DIR.iterdir())


@pytest.mark.parametrize("kind", ("existing", "symlink"))
def test_preexisting_marker_never_passes_as_new_pause(monkeypatch, isolated_hooks, kind, tmp_path):
    enabled(monkeypatch, "after_claim")
    marker = faults.marker_path("after_claim", RUN)
    target = tmp_path / "keep"
    target.write_text("unchanged")
    if kind == "symlink":
        marker.symlink_to(target)
    else:
        marker.write_text("stale")
    with pytest.raises(FileExistsError):
        faults.pause_at("after_claim", TASK, **metadata("after_claim"))
    isolated_hooks.assert_not_called()
    assert target.read_text() == "unchanged"


@pytest.mark.parametrize("point,run_id", (("../escape", RUN), ("after_claim", "../escape")))
def test_marker_path_is_not_arbitrary(point, run_id):
    with pytest.raises(ValueError):
        faults.marker_path(point, run_id)


def test_actual_service_calls_include_durable_task_event_attempt_identity(monkeypatch):
    runtime = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///:memory:", lease_seconds=30))
    migrate(runtime.engine)
    seen = []

    def inspect(point, task_id, **fields):
        with runtime.sessions() as session:
            task = session.get(Task, task_id)
            assert task and task.result_id is None
            if point == "after_outbox_publish":
                outbox = session.get(Outbox, fields["event_id"])
                assert outbox.task_id == task_id and outbox.sent_at is None
            else:
                assert task.status == "running" and task.attempt_id == fields["attempt_id"]
                assert task.fence == fields["fence"]
                assert session.get(Attempt, task.attempt_id).outcome == "running"
                document = runtime.documents.get(task_id + ":" + task.attempt_id)
                assert bool(document) == (point == "after_mongo_save")
            seen.append(point)

    monkeypatch.setattr("backend.service.pause_at", inspect)
    try:
        task = runtime.tasks.create("synthetic-owner", "synthetic-key", "synthetic input", "trace")
        runtime.tasks.relay_once()
        runtime.tasks.receive(runtime.bus.messages[0][1])
        assert runtime.tasks.execute_once()
        assert seen == ["after_outbox_publish", "after_claim", "after_mongo_save"]
        assert runtime.tasks.get("synthetic-owner", task["id"])["status"] == "succeeded"
    finally:
        runtime.engine.dispose()


def test_default_service_execution_has_no_pause_or_marker(isolated_hooks):
    runtime = Runtime(Settings(mode="test", database_url="sqlite+pysqlite:///:memory:"))
    migrate(runtime.engine)
    try:
        runtime.tasks.create("owner", "key", "synthetic", "trace")
        runtime.tasks.relay_once()
        runtime.tasks.receive(runtime.bus.messages[0][1])
        assert runtime.tasks.execute_once()
        with runtime.sessions() as session:
            assert session.scalar(select(Task)).status == "succeeded"
        isolated_hooks.assert_not_called()
        assert not list(faults.MARKER_DIR.iterdir())
    finally:
        runtime.engine.dispose()


def test_worker_inbox_hook_is_after_receive_before_commit_with_real_message_metadata(monkeypatch, tmp_path):
    from backend import worker

    event = {"event_id": EVENT, "task_id": TASK}
    order = []

    class StopProbe(Exception):
        pass

    message = SimpleNamespace(
        error=lambda: None,
        value=lambda: json.dumps(event).encode(),
        topic=lambda: "agent.tasks",
        partition=lambda: 0,
        offset=lambda: 7,
    )
    consumer = Mock()
    consumer.poll.side_effect = [message, StopProbe()]
    consumer.commit.side_effect = lambda **kwargs: order.append(("commit", kwargs))
    settings = SimpleNamespace(mode="production", topic="agent.tasks", dlq_topic="dlq", kafka_servers="none")
    runtime = SimpleNamespace(settings=settings, bus=Mock(), tasks=Mock())
    runtime.tasks.receive.side_effect = lambda value: order.append(("receive", value))
    monkeypatch.setattr(worker, "Runtime", lambda: runtime)
    monkeypatch.setattr(worker, "HEARTBEAT", tmp_path / "heartbeat")
    monkeypatch.setattr(worker.threading, "Thread", Mock())
    monkeypatch.setattr(worker, "pause_at", lambda *args, **kwargs: order.append(("hook", args, kwargs)))
    monkeypatch.setitem(sys.modules, "confluent_kafka", SimpleNamespace(Consumer=lambda _: consumer))
    monkeypatch.setattr(sys, "argv", ["worker"])
    with pytest.raises(StopProbe):
        worker.main()
    assert order == [
        ("receive", event),
        (
            "hook",
            ("after_inbox_commit", TASK),
            {"event_id": EVENT, "topic": "agent.tasks", "partition": 0, "offset": 7},
        ),
        ("commit", {"message": message, "asynchronous": False}),
    ]
    consumer.close.assert_called_once()


@pytest.fixture
def crash_probe(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[2] / "tests/integration/crash_probe.py"
    spec = importlib.util.spec_from_file_location("crash_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPORTS", tmp_path)
    monkeypatch.setattr(module, "STATE", tmp_path / "crash-state.json")
    return module


def test_crash_report_four_incomplete_windows_are_not_pass_and_contains_no_private_data(crash_probe):
    state = {
        "cases": {
            point: {"phases": [], "session": {"csrf": "PRIVATE_TOKEN"}, "event": {"prompt": "PRIVATE_PROMPT"}}
            for point in POINTS
        }
    }
    crash_probe.private_write(state)
    assert crash_probe.STATE.stat().st_mode & 0o777 == 0o600
    crash_probe.report(state)
    report = json.loads((crash_probe.REPORTS / "crash-windows.json").read_text())
    assert report["status"] == "incomplete" and len(report["windows"]) == 4
    assert {case["status"] for case in report["windows"]} == {"incomplete"}
    for path in ("crash-windows.json", "crash-windows.xml"):
        content = (crash_probe.REPORTS / path).read_text()
        assert "PRIVATE" not in content and "csrf" not in content and "prompt" not in content


def test_cleanup_failure_marks_report_failed_even_after_recovery(crash_probe, monkeypatch):
    state = {"cases": {point: {"phases": list(crash_probe.PHASES)} for point in POINTS}}
    crash_probe.private_write(state)
    monkeypatch.setattr(sys, "argv", ["probe", "cleanup"])
    monkeypatch.setenv("TEST_HOOK_POINT", POINTS[-1])
    monkeypatch.setenv("TEST_CLEANUP_OK", "0")
    crash_probe.main()
    report = json.loads((crash_probe.REPORTS / "crash-windows.json").read_text())
    assert report["status"] == "failed" and report["cleanup_verified"] is False
    assert report["windows"][-1]["status"] == "failed"
    assert not crash_probe.STATE.exists()


def test_crash_probe_failure_does_not_print_exception_response_or_traceback(crash_probe, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["probe", "init"])
    crash_probe.main()
    monkeypatch.setattr(sys, "argv", ["probe", "prepare"])
    monkeypatch.setenv("TEST_HOOK_POINT", POINTS[0])
    monkeypatch.setattr(crash_probe, "prepare", Mock(side_effect=RuntimeError("PRIVATE_COOKIE_AND_URL")))
    with pytest.raises(SystemExit) as result:
        crash_probe.main()
    assert result.value.code == 1
    captured = capsys.readouterr()
    assert "FAIL:" in captured.err and "PRIVATE" not in captured.err and "Traceback" not in captured.err
    report = json.loads((crash_probe.REPORTS / "crash-windows.json").read_text())
    assert report["windows"][0]["status"] == "failed"


def test_fault_only_lease_exceeds_unchanged_agent_persistence_reserve():
    root = Path(__file__).resolve().parents[2]
    overlay = (root / "compose.fault-test.yaml").read_text()
    assert "LEASE_SECONDS: '30'" in overlay and "LAB_TEST_RUN_ID:" in overlay
    assert "task.lease_until - time.time() - 15" in (root / "backend/agent.py").read_text()


def test_direct_container_probe_has_explicit_backend_import_path():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/test-crash-windows.sh").read_text()
    assert "-e PYTHONPATH=/app" in script
    assert "/tests/integration/crash_probe.py" in script


@pytest.mark.parametrize("status", ("ready", "running", "succeeded"))
def test_publication_boundary_allows_valid_concurrent_task_progress(crash_probe, monkeypatch, status):
    # Regression for the old false oracle: only relay is paused, not consumer/executor.
    now = crash_probe.time.time()
    case = {"task_id": TASK, "run_id": RUN, "event": {"event_id": EVENT}}
    marker = {
        "version": 1,
        "point": POINTS[0],
        "task_id": TASK,
        "run_id": RUN,
        "event_id": EVENT,
        "created_at": now,
        "expires_at": now + faults.PAUSE_SECONDS,
    }
    monkeypatch.setenv("TEST_HOOK_MARKER", json.dumps(marker))
    monkeypatch.setattr(crash_probe, "task_row", lambda _: {"id": TASK, "status": status})
    monkeypatch.setattr(crash_probe, "outbox_row", lambda _: {"id": EVENT, "sent_at": None})
    monkeypatch.setattr(crash_probe, "target_records", lambda _: [{"partition": 0, "offset": 42}])
    crash_probe.boundary(case, POINTS[0])
    assert case["marker"] == marker


@pytest.mark.parametrize("failure", ("already_sent", "wrong_event", "not_in_kafka"))
def test_publication_boundary_still_requires_causal_delivery_evidence(crash_probe, monkeypatch, failure):
    now = crash_probe.time.time()
    case = {"task_id": TASK, "run_id": RUN, "event": {"event_id": EVENT}}
    marker = {
        "version": 1,
        "point": POINTS[0],
        "task_id": TASK,
        "run_id": RUN,
        "event_id": EVENT,
        "created_at": now,
        "expires_at": now + faults.PAUSE_SECONDS,
    }
    monkeypatch.setenv("TEST_HOOK_MARKER", json.dumps(marker))
    monkeypatch.setattr(crash_probe, "task_row", lambda _: {"id": TASK, "status": "succeeded"})
    monkeypatch.setattr(
        crash_probe,
        "outbox_row",
        lambda _: {
            "id": str(uuid4()) if failure == "wrong_event" else EVENT,
            "sent_at": now if failure == "already_sent" else None,
        },
    )
    monkeypatch.setattr(crash_probe, "target_records", lambda _: [] if failure == "not_in_kafka" else [{}])
    with pytest.raises(AssertionError):
        crash_probe.boundary(case, POINTS[0])


@pytest.mark.parametrize("committed,passes", ((-1001, True), (41, True), (42, True), (43, False)))
def test_inbox_boundary_checks_next_offset_not_committed_target(crash_probe, monkeypatch, committed, passes):
    now = crash_probe.time.time()
    case = {"task_id": TASK, "run_id": RUN, "event": {"event_id": EVENT}}
    marker = {
        "version": 1,
        "point": POINTS[1],
        "task_id": TASK,
        "run_id": RUN,
        "created_at": now,
        "expires_at": now + faults.PAUSE_SECONDS,
        **metadata(POINTS[1]),
    }
    monkeypatch.setenv("TEST_HOOK_MARKER", json.dumps(marker))
    monkeypatch.setattr(crash_probe, "task_row", lambda _: {"id": TASK, "status": "succeeded"})
    monkeypatch.setattr(crash_probe, "outbox_row", lambda _: {"id": EVENT, "sent_at": now})
    monkeypatch.setattr(crash_probe, "rows", lambda *args, **kwargs: [{"event_id": EVENT}])
    monkeypatch.setattr(crash_probe, "committed", lambda _: committed)
    monkeypatch.setattr(crash_probe, "target_records", lambda _: [{"partition": 0, "offset": 42}])
    if passes:
        crash_probe.boundary(case, POINTS[1])
    else:
        with pytest.raises(AssertionError, match="already committed"):
            crash_probe.boundary(case, POINTS[1])


def test_report_rejects_unknown_phase_without_leaking_its_value(crash_probe):
    state = {"cases": {point: {"phases": []} for point in POINTS}}
    state["cases"][POINTS[0]]["phases"] = ["PRIVATE_OR_MALFORMED_PHASE"]
    crash_probe.report(state)
    result = (crash_probe.REPORTS / "crash-windows.json").read_text()
    assert "PRIVATE" not in result and json.loads(result)["status"] == "failed"
    assert "PRIVATE" not in (crash_probe.REPORTS / "crash-windows.xml").read_text()


def test_recovery_uses_actual_result_dto_and_agent_steps_attempt_link(crash_probe, monkeypatch):
    import httpx

    from backend.app import ResultResponse

    # Construct with the production response model, not a hand-invented extra attempt_id field.
    result = ResultResponse(
        task_id=TASK,
        content="synthetic",
        model_mode="deterministic",
        cache_status="miss",
        execution_kind="single_agent",
        controller_mode="scripted_test",
    ).model_dump()
    assert "attempt_id" not in result
    steps = {"availability": "committed", "items": [{"kind": "final", "attempt_id": ATTEMPT}]}
    http = Mock()
    http.__enter__ = Mock(return_value=http)
    http.__exit__ = Mock(return_value=False)
    http.get.side_effect = [httpx.Response(200, json=result), httpx.Response(200, json=steps)]
    monkeypatch.setattr(crash_probe, "client", lambda _: http)
    crash_probe.committed_api({}, {"id": TASK, "attempt_id": ATTEMPT})


@pytest.mark.parametrize("point", POINTS)
def test_killed_phase_rechecks_durable_boundary_before_recovery(crash_probe, monkeypatch, point):
    state = {"cases": {name: {"phases": []} for name in POINTS}}
    case = state["cases"][point]
    case.update(phases=list(crash_probe.PHASES[:2]), marker={"expires_at": crash_probe.time.time() + 30})
    crash_probe.private_write(state)
    snapshots = []
    observed = Mock(
        side_effect=lambda current, name: snapshots.append((json.loads(json.dumps(current)), name))
    )
    monkeypatch.setattr(crash_probe, "durable_boundary", observed)
    monkeypatch.setattr(sys, "argv", ["probe", "killed"])
    monkeypatch.setenv("TEST_HOOK_POINT", point)
    monkeypatch.setenv("TEST_KILL_VERIFIED", "1")
    crash_probe.main()
    observed.assert_called_once()
    assert snapshots == [(case, point)]
    updated = json.loads(crash_probe.STATE.read_text())
    assert updated["cases"][point]["phases"] == list(crash_probe.PHASES[:3])


@pytest.mark.parametrize("point", POINTS)
def test_killed_phase_rejects_advanced_or_missing_durable_evidence(crash_probe, monkeypatch, point):
    state = {"cases": {name: {"phases": []} for name in POINTS}}
    marker = {"expires_at": crash_probe.time.time() + 30, **metadata(point)}
    case = state["cases"][point]
    case.update(phases=list(crash_probe.PHASES[:2]), marker=marker, task_id=TASK, event={"event_id": EVENT})
    crash_probe.private_write(state)
    monkeypatch.setattr(sys, "argv", ["probe", "killed"])
    monkeypatch.setenv("TEST_HOOK_POINT", point)
    monkeypatch.setenv("TEST_KILL_VERIFIED", "1")
    monkeypatch.setattr(crash_probe, "outbox_row", lambda _: {"id": EVENT, "sent_at": 1})
    monkeypatch.setattr(
        crash_probe,
        "task_row",
        lambda _: {
            "id": TASK,
            "status": "succeeded" if point == "after_claim" else "running",
            "result_id": None,
            "attempt_id": ATTEMPT,
            "fence": 1,
        },
    )
    monkeypatch.setattr(
        crash_probe,
        "rows",
        lambda *args, **kwargs: (
            [{"event_id": EVENT}]
            if point == "after_inbox_commit"
            else [{"id": ATTEMPT, "fence": 1, "outcome": "running"}]
        ),
    )
    monkeypatch.setattr(crash_probe, "committed", lambda _: 43)
    monkeypatch.setattr(crash_probe, "mongo_document", lambda _: None)
    with pytest.raises(SystemExit) as failure:
        crash_probe.main()
    assert failure.value.code == 1
    updated = json.loads(crash_probe.STATE.read_text())
    assert updated["cases"][point]["failed"] is True
    assert updated["cases"][point]["phases"] == list(crash_probe.PHASES[:2])


@pytest.mark.parametrize("failed_writer", ("private_write", "report"))
def test_report_io_failure_never_escapes_with_raw_exception(crash_probe, monkeypatch, capsys, failed_writer):
    monkeypatch.setattr(crash_probe, failed_writer, Mock(side_effect=OSError("PRIVATE_PATH_OR_SECRET")))
    monkeypatch.setattr(sys, "argv", ["probe", "init"])
    with pytest.raises(SystemExit) as failure:
        crash_probe.main()
    assert failure.value.code == 1
    captured = capsys.readouterr()
    assert "NOT PASS" in captured.err and "PRIVATE" not in captured.err and "Traceback" not in captured.err
