"""Offline UNIT checks of the probe itself; MockTransport is NOT MySQL integration evidence."""

import importlib.util
import json
import os
import stat
import subprocess
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "mysql_outage_probe", Path(__file__).resolve().parents[2] / "tests/integration/outage_probe.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.fixture
def clock(monkeypatch):
    clock = types.SimpleNamespace(now=0)
    clock.monotonic = lambda: clock.now

    def advance(seconds):
        clock.now += seconds

    clock.sleep = advance
    monkeypatch.setattr(probe, "time", clock)
    return clock


def ready(up=True, **changes):
    body = {
        "mode": "production",
        "model_mode": "deterministic",
        "status": "ready" if up else "not_ready",
        "dependencies": {"mysql": "up" if up else "down", "mongo": "up", "kafka": "up"},
        **changes,
    }
    return httpx.Response(200 if up else 503, json=body)


def error(status=503, code="database_unavailable", message="Database temporarily unavailable"):
    return httpx.Response(
        status,
        json={"error": {"code": code, "message": message}, "request_id": "synthetic-request"},
        headers={"X-Request-ID": "synthetic-request"},
    )


def test_unit_readiness_waits_for_actual_http_state(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return ready(up=len(calls) > 1)

    with httpx.Client(base_url="http://unit.invalid", transport=httpx.MockTransport(handler)) as client:
        probe.wait_mysql_readiness(client, up=True, timeout=3)
    assert len(calls) == 2 and clock.now == 1
    assert all(request.extensions["timeout"]["read"] <= 3 for request in calls)


def test_unit_transport_timeout_is_not_evidence_of_http_503(clock):
    def timeout(request):
        raise httpx.ReadTimeout("secret driver details must not be reported", request=request)

    with httpx.Client(base_url="http://unit.invalid", transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(AssertionError, match="required HTTP state not observed"):
            probe.wait_mysql_readiness(client, up=False, timeout=2)
    assert clock.now == 2


@pytest.mark.parametrize("changes", [{"mode": "test"}, {"model_mode": "live"}])
def test_unit_readiness_rejects_fake_adapters_and_live_mode(changes):
    with httpx.Client(
        base_url="http://unit.invalid", transport=httpx.MockTransport(lambda _: ready(**changes))
    ) as client:
        with pytest.raises(AssertionError):
            probe.wait_mysql_readiness(client, up=True)


def test_unit_wrong_dependency_outage_cannot_pass_mysql_probe(clock):
    response = ready(False, dependencies={"mysql": "up", "mongo": "down", "kafka": "up"})
    with httpx.Client(
        base_url="http://unit.invalid", transport=httpx.MockTransport(lambda _: response)
    ) as client:
        with pytest.raises(AssertionError, match="deadline"):
            probe.wait_mysql_readiness(client, up=False, timeout=2)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(202, json={"id": "incorrectly-accepted"}),
        httpx.Response(200, json={"content": "incorrectly-cached"}),
        error(code="document_unavailable"),
        error(message="Traceback mysql+pymysql://private"),
        httpx.Response(503, json={"error": {"code": "database_unavailable", "message": "safe"}}),
    ],
)
def test_unit_sql_error_check_rejects_false_success_wrong_failure_and_leaks(response):
    with pytest.raises(AssertionError) as exc:
        probe.checked_error(response)
    assert "incorrectly" not in str(exc.value) and "mysql+pymysql" not in str(exc.value)


def test_unit_sql_error_requires_consistent_request_id():
    response = error()
    response.headers["X-Request-ID"] = "wrong-request"
    with pytest.raises(AssertionError, match="request ID"):
        probe.checked_error(response)


def outage_state():
    return {
        "scenario": "mysql-outage",
        "phases": list(probe.MYSQL_PHASES[:2]),
        "owner": {"cookies": {"lab_session": "owner-private"}, "csrf": "owner-csrf", "owner_id": "owner"},
        "stranger": {"cookies": {"lab_session": "stranger-private"}, "csrf": "stranger-csrf"},
        "committed": {"id": "committed", "result_id": "result"},
        "pending_id": "pending",
        "blocked_key": "private-key",
    }


@pytest.mark.parametrize("bypass", [False, True])
def test_unit_outage_probe_checks_actual_authenticated_requests_and_warm_cache(monkeypatch, bypass):
    requests, cache_checks = [], []

    def handler(request):
        requests.append(request)
        if request.url.path == "/readyz":
            return ready(False)
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        assert request.headers.get("cookie") in ("lab_session=owner-private", "lab_session=stranger-private")
        if bypass and request.url.path.endswith("/results"):
            return httpx.Response(200, json={"content": "cache incorrectly bypassed SQL"})
        if request.method == "POST":
            assert request.headers["X-CSRF-Token"] == "owner-csrf"
            assert request.headers["Idempotency-Key"] == "private-key"
        return error()

    def client(session):
        return httpx.Client(
            base_url="http://unit.invalid",
            cookies=session["cookies"],
            headers={"X-CSRF-Token": session["csrf"]},
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(probe, "mysql_client", client)
    monkeypatch.setattr(probe, "assert_warm_cache", lambda result_id: cache_checks.append(result_id))
    if bypass:
        with pytest.raises(AssertionError, match="expected HTTP 503"):
            probe.mysql_phase("mysql-unavailable", outage_state())
    else:
        probe.mysql_phase("mysql-unavailable", outage_state())
        assert cache_checks == ["result", "result"]
        assert [(r.method, r.url.path) for r in requests] == [
            ("GET", "/readyz"),
            ("GET", "/healthz"),
            ("GET", "/api/v1/tasks/committed/results"),
            ("GET", "/api/v1/tasks/committed/results"),
            ("POST", "/api/v1/tasks"),
            ("GET", "/api/v1/tasks"),
            ("GET", "/api/v1/tasks/pending"),
            ("GET", "/api/v1/tasks/committed/agent-steps"),
        ]


@pytest.mark.parametrize("change", [{"status": "succeeded"}, {"result_id": "orphan"}, {"attempt_count": 1}])
def test_unit_pending_proof_rejects_false_success_or_racing_executor(monkeypatch, change):
    monkeypatch.setattr(
        probe,
        "mysql_task",
        lambda _: {
            "id": "pending",
            "owner_id": "owner",
            "status": "pending",
            "result_id": None,
            "attempt_count": 0,
            **change,
        },
    )
    with pytest.raises(AssertionError, match="durable work pending"):
        probe.assert_pending(outage_state())


def test_unit_pending_proof_requires_same_unsent_outbox_after_restart(monkeypatch):
    monkeypatch.setattr(
        probe,
        "mysql_task",
        lambda _: {
            "id": "pending",
            "owner_id": "owner",
            "status": "pending",
            "result_id": None,
            "attempt_count": 0,
        },
    )
    monkeypatch.setattr(probe, "mysql_rows", lambda *args, **kwargs: [{"id": "new-event", "sent_at": None}])
    state = {**outage_state(), "pending_outbox_id": "original-event"}
    with pytest.raises(AssertionError, match="original outbox"):
        probe.assert_pending(state)


def test_unit_private_state_is_mode_0600_and_rejects_symlink(monkeypatch, tmp_path):
    path = tmp_path / "outage-state.json"
    monkeypatch.setattr(probe, "STATE", path)
    probe.write_state(outage_state())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.unlink()
    target = tmp_path / "do-not-overwrite"
    target.write_text("untouched")
    path.symlink_to(target)
    with pytest.raises(OSError):
        probe.write_state(outage_state())
    assert target.read_text() == "untouched"


def test_unit_report_marks_incomplete_and_single_complete_scenario(monkeypatch, tmp_path):
    report = tmp_path / "mysql-outage.xml"
    monkeypatch.setattr(probe, "MYSQL_REPORT", report)
    probe.write_mysql_report(list(probe.MYSQL_PHASES[:2]))
    assert ET.parse(report).getroot().attrib["skipped"] == "1"
    probe.write_mysql_report(list(probe.MYSQL_PHASES))
    suite = ET.parse(report).getroot()
    assert suite.attrib["tests"] == "1" and suite.attrib["skipped"] == "0" and suite.attrib["failures"] == "0"
    assert len(suite.findall("testcase")) == 1
    assert "NOT a pytest test" in report.read_text()


def test_unit_failed_probe_report_and_console_do_not_echo_exception_secrets(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(probe, "STATE", tmp_path / "outage-state.json")
    monkeypatch.setattr(probe, "MYSQL_REPORT", tmp_path / "mysql-outage.xml")
    probe.write_state(outage_state())

    def fail(*args):
        raise RuntimeError("mysql+pymysql://private-db secret-cookie secret-key")

    monkeypatch.setattr(probe, "mysql_phase", fail)
    with pytest.raises(SystemExit) as exc:
        probe.run_mysql_phase("mysql-unavailable")
    assert exc.value.code == 1
    output = capsys.readouterr().err + probe.MYSQL_REPORT.read_text()
    assert "RuntimeError" in output
    assert not any(
        value in output for value in ("private-db", "secret-cookie", "secret-key", "owner-private")
    )
    assert ET.parse(probe.MYSQL_REPORT).getroot().attrib["failures"] == "1"


def test_unit_probe_rejects_out_of_order_phase(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "STATE", tmp_path / "outage-state.json")
    monkeypatch.setattr(probe, "MYSQL_REPORT", tmp_path / "mysql-outage.xml")
    probe.write_state(outage_state())
    with pytest.raises(SystemExit):
        probe.run_mysql_phase("mysql-complete")
    assert json.loads(probe.STATE.read_text())["phases"] == list(probe.MYSQL_PHASES[:2])


def test_unit_result_fingerprint_ignores_only_cache_status():
    baseline = {"content": "synthetic", "model_mode": "deterministic", "cache_status": "miss"}
    assert probe.result_digest(baseline) == probe.result_digest({**baseline, "cache_status": "hit"})
    assert probe.result_digest(baseline) != probe.result_digest({**baseline, "content": "changed"})


@pytest.mark.parametrize("mode", ["success", "phase-failure", "restore-failure"])
def test_unit_shell_orchestration_preserves_exit_status_and_restore_order(tmp_path, mode):
    """CLI doubles only: check shell control flow without a Docker daemon or .env."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[2] / "scripts/test-integration.sh"
    script = scripts / source.name
    script.write_text(source.read_text())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
if [[ "$STUB_MODE" = phase-failure && "$*" = *"outage_probe.py mysql-unavailable" ]]; then exit 1; fi
if [[ "$STUB_MODE" = restore-failure && "$*" = *"--wait-timeout 180 mysql redis mongo kafka" ]]; then exit 1; fi
""")
    docker.chmod(0o700)
    # The log-redaction program is independently tested; this unit test only
    # observes the orchestration path and must not execute other project scripts.
    python = bin_dir / "python"
    python.write_text("#!/usr/bin/env bash\nexit 0\n")
    python.chmod(0o700)
    log = tmp_path / "commands"
    run = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "STUB_LOG": str(log),
            "STUB_MODE": mode,
        },
    )
    commands = log.read_text().splitlines()
    dependency_restore = "compose up -d --no-deps --wait --wait-timeout 180 mysql redis mongo kafka"
    worker_restore = "compose up -d --no-deps --force-recreate --wait --wait-timeout 180 worker"
    assert dependency_restore in commands
    assert run.returncode == (0 if mode == "success" else 1)
    if mode == "restore-failure":
        assert worker_restore not in commands
    else:
        assert commands.index(dependency_restore) < commands.index(worker_restore)
    if mode == "phase-failure":
        assert not any(command.endswith("outage_probe.py mysql-complete") for command in commands)
    else:
        phases = [command.rsplit(" ", 1)[-1] for command in commands if "outage_probe.py mysql-" in command]
        assert phases == list(probe.MYSQL_PHASES)
    assert not (tmp_path / ".env").exists()
