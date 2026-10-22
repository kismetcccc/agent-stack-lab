"""Offline helper tests only; these doubles do NOT prove Docker ignore semantics."""

import importlib.util
import io
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test-build-context.py"
spec = importlib.util.spec_from_file_location("build_context_acceptance", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def write_archive(path, paths):
    with tarfile.open(path, "w") as archive:
        for relative in paths:
            member = tarfile.TarInfo(f"./context/{relative}")
            member.size = len(checker.SENTINEL)
            archive.addfile(member, io.BytesIO(checker.SENTINEL))


def test_fixture_reads_only_public_ignore_and_creates_synthetic_files(tmp_path):
    context = tmp_path / "context"
    checker.create_fixture(checker.IGNORE_FILE, context)
    actual = {path.relative_to(context).as_posix() for path in context.rglob("*") if path.is_file()}
    assert actual == set(checker.PRIVATE_PATHS + checker.PUBLIC_PATHS) | {".dockerignore", "Dockerfile"}
    assert (context / ".dockerignore").read_bytes() == checker.IGNORE_FILE.read_bytes()
    assert (context / "Dockerfile").read_text() == "FROM scratch\nCOPY . /context/\n"
    assert stat.S_IMODE(context.stat().st_mode) == 0o700
    for relative in checker.PRIVATE_PATHS + checker.PUBLIC_PATHS:
        assert (context / relative).read_bytes() == checker.SENTINEL


def test_archive_accepts_all_public_sentinels_without_extracting(tmp_path):
    archive = tmp_path / "filesystem.tar"
    write_archive(archive, checker.PUBLIC_PATHS)
    # Docker export may include its own metadata, e.g. /etc/hosts.
    with tarfile.open(archive, "a") as contents:
        contents.addfile(tarfile.TarInfo("etc/hosts"), io.BytesIO())
    checker.verify_archive(archive)
    assert set(tmp_path.iterdir()) == {archive}


@pytest.mark.parametrize("private", [
    ".env", "config/.env.example", "config/deep/.secrets/config.txt",
    "config/tls/private.key", "data/backup.sql",
    "local.sqlite", "config/deep/local.db-wal", "config/deep/local.sqlite3-journal",
])
def test_archive_rejects_private_sentinel(tmp_path, private):
    archive = tmp_path / "filesystem.tar"
    write_archive(archive, (*checker.PUBLIC_PATHS, private))
    with pytest.raises(checker.CheckFailed, match="private synthetic paths"):
        checker.verify_archive(archive)


@pytest.mark.parametrize("public", [".env.example", "backend/app.py", "backend/migrations/001_context_probe.sql"])
def test_archive_rejects_missing_public_source(tmp_path, public):
    archive = tmp_path / "filesystem.tar"
    write_archive(archive, [path for path in checker.PUBLIC_PATHS if path != public])
    with pytest.raises(checker.CheckFailed, match="public synthetic paths"):
        checker.verify_archive(archive)


class DockerDouble:
    """Simulates orchestration/cleanup, never Docker's filtering algorithm."""

    def __init__(self, fail_at=None, leak=False):
        self.fail_at = fail_at
        self.leak = leak
        self.calls = []
        self.context = None

    def __call__(self, docker, arguments, *, stage, timeout=30, cwd=None):
        self.calls.append(arguments)
        operation = " ".join(arguments[:2]) if arguments[0] != "build" else "build"
        if cwd is not None:
            self.context = cwd
            assert cwd.name == "context"
            assert stat.S_IMODE(cwd.parent.stat().st_mode) == 0o700
        if operation == self.fail_at:
            raise checker.CheckFailed(f"{stage}: synthetic failure")
        if operation == "container export":
            paths = (*checker.PUBLIC_PATHS, ".env") if self.leak else checker.PUBLIC_PATHS
            write_archive(Path(arguments[arguments.index("--output") + 1]), paths)
        if operation == "container ls":
            return "c" * 64
        if operation == "image ls":
            return "sha256:" + "a" * 64
        return ""


def test_orchestration_is_registry_free_unstarted_and_exactly_scoped(monkeypatch):
    fake = DockerDouble()
    monkeypatch.setattr(checker, "docker_command", fake)
    checker.check_context("docker-double")
    build, create, export, container_list, container_rm, image_list, image_rm = fake.calls
    assert build[0] == "build" and build[-1] == "."
    assert "--pull=false" in build and "--network=none" in build
    assert "--pull=never" in create and "/__never_executed__" in create
    assert create[:2] == ["container", "create"]
    name = create[create.index("--name") + 1]
    image = build[build.index("--tag") + 1]
    label = build[build.index("--label") + 1]
    assert image == f"{name}:test"
    assert export[-1] == name
    assert f"name=^/{name}$" in container_list
    assert f"reference={image}" in image_list
    assert f"label={label}" in container_list and f"label={label}" in image_list
    assert container_rm == ["container", "rm", "c" * 64]
    assert image_rm == ["image", "rm", "--no-prune", "sha256:" + "a" * 64]
    assert not fake.context.parent.exists()  # No retained fixture or tar artifact.


@pytest.mark.parametrize("stage", ["build", "container create", "container export"])
def test_command_failure_still_cleans_up_uncertain_created_resources(monkeypatch, stage):
    fake = DockerDouble(fail_at=stage)
    monkeypatch.setattr(checker, "docker_command", fake)
    with pytest.raises(checker.CheckFailed, match="synthetic failure"):
        checker.check_context("docker-double")
    assert ["image", "rm", "--no-prune", "sha256:" + "a" * 64] in fake.calls
    if stage != "build":
        assert ["container", "rm", "c" * 64] in fake.calls
    else:
        assert not any(call[:2] == ["container", "rm"] for call in fake.calls)
    assert not fake.context.parent.exists()


@pytest.mark.parametrize("failure", ["container ls", "container rm", "image ls", "image rm"])
def test_cleanup_failure_is_reported_and_other_cleanup_is_attempted(monkeypatch, failure):
    fake = DockerDouble(fail_at=failure)
    monkeypatch.setattr(checker, "docker_command", fake)
    with pytest.raises(checker.CheckFailed, match="cleanup"):
        checker.check_context("docker-double")
    assert any(call[:2] == ["image", "ls"] for call in fake.calls)
    assert not fake.context.parent.exists()


def test_filter_failure_still_removes_container_and_image(monkeypatch):
    fake = DockerDouble(leak=True)
    monkeypatch.setattr(checker, "docker_command", fake)
    with pytest.raises(checker.CheckFailed, match="private synthetic paths"):
        checker.check_context("docker-double")
    assert ["container", "rm", "c" * 64] in fake.calls
    assert ["image", "rm", "--no-prune", "sha256:" + "a" * 64] in fake.calls


@pytest.mark.parametrize("identities", ["not-an-id", "a" * 64 + "\n" + "b" * 64])
def test_cleanup_refuses_ambiguous_identity(monkeypatch, identities):
    calls = []

    def fake(docker, arguments, **kwargs):
        calls.append(arguments)
        return identities

    monkeypatch.setattr(checker, "docker_command", fake)
    with pytest.raises(checker.CheckFailed, match="nothing removed"):
        checker.cleanup_resource("docker-double", "image", "synthetic:test", "synthetic-token")
    assert len(calls) == 1


def test_absent_owned_resource_requires_no_removal(monkeypatch):
    calls = []

    def fake(docker, arguments, **kwargs):
        calls.append(arguments)
        return ""

    monkeypatch.setattr(checker, "docker_command", fake)
    checker.cleanup_resource("docker-double", "container", "synthetic", "synthetic-token")
    assert len(calls) == 1
    assert calls[0][:2] == ["container", "ls"]


@pytest.mark.parametrize("failure", ["exit", "timeout", "oserror"])
def test_subprocess_errors_are_bounded_and_sanitized(monkeypatch, failure):
    sensitive = "SYNTHETIC-CONNECTION-DETAIL-DO-NOT-PRINT"

    def fake(command, **kwargs):
        assert kwargs["timeout"] == 7
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["stdin"] is subprocess.DEVNULL
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 7, output=sensitive, stderr=sensitive)
        if failure == "oserror":
            raise OSError(sensitive)
        return subprocess.CompletedProcess(command, 1, stdout=sensitive.encode())

    monkeypatch.setattr(checker.subprocess, "run", fake)
    with pytest.raises(checker.CheckFailed) as error:
        checker.docker_command("docker-double", ["version"], stage="safe-stage", timeout=7)
    assert sensitive not in str(error.value)
    assert "safe-stage" in str(error.value)


@pytest.mark.parametrize("available", [False, True])
def test_missing_cli_or_daemon_is_not_run_not_pass(monkeypatch, capsys, available):
    monkeypatch.setattr(checker.shutil, "which", lambda _: "docker-double" if available else None)

    def unavailable(*args, **kwargs):
        raise checker.CheckFailed("SYNTHETIC-CONNECTION-DETAIL-DO-NOT-PRINT")

    monkeypatch.setattr(checker, "docker_command", unavailable)
    monkeypatch.setattr(checker, "check_context", lambda *_: pytest.fail("must not build"))
    assert checker.main() == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "NOT RUN" in captured.err
    assert "SYNTHETIC-CONNECTION" not in captured.err


@pytest.mark.parametrize("failure", [checker.CheckFailed("cleanup synthetic image failed"), OSError("private")])
def test_main_failure_never_prints_pass_or_raw_io_errors(monkeypatch, capsys, failure):
    monkeypatch.setattr(checker.shutil, "which", lambda _: "docker-double")
    monkeypatch.setattr(checker, "docker_command", lambda *args, **kwargs: "synthetic-version")

    def fail(*args):
        raise failure

    monkeypatch.setattr(checker, "check_context", fail)
    assert checker.main() == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "FAIL:" in captured.err
    assert "private" not in captured.err
