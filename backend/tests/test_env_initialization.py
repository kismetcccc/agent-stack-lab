"""Initializer tests touch only private temporary directories and synthetic data."""

import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "infra-init-env.py"
spec = importlib.util.spec_from_file_location("env_initialization", SCRIPT)
initializer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(initializer)
DUMMY = b"SYNTHETIC-KEY-NOT-A-REAL-CREDENTIAL"


@pytest.fixture
def destination(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path / ".env"


def run(path, *args):
    # Sanitized environment; this subprocess never loads the project's real .env.
    return subprocess.run([sys.executable, str(SCRIPT), "--path", str(path), *args],
                          capture_output=True, check=False, env={"PATH": os.defpath})


def assert_clean(path):
    assert set(path.parent.iterdir()) <= {path}


def write(path, data, mode=0o600):
    path.write_bytes(data)
    path.chmod(mode)


def test_import_has_no_initialization_side_effect():
    assert callable(initializer.main)


def test_fresh_atomic_create_and_default_refusal(destination):
    created = run(destination)
    assert created.returncode == 0
    data = destination.read_bytes()
    assert data.startswith(initializer.HEADER)
    assert data.endswith(b"LAB_PORT=8080\n")
    values = []
    for key in initializer.KEYS:
        value = re.search(key + rb"=([a-f0-9]{48})\n", data)[1]
        assert value not in created.stdout + created.stderr
        values.append(value)
    assert len(set(values)) == 4
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    refused = run(destination)
    assert refused.returncode == 1
    assert destination.read_bytes() == data
    assert b"exists" in refused.stderr
    assert_clean(destination)


def test_default_refusal_does_not_parse_or_change_existing_bytes(destination):
    data = b"malformed\xff\x00\r\nMODEL_API_KEY=" + DUMMY
    write(destination, data)
    before = initializer.fingerprint(destination.stat())
    result = run(destination)
    assert result.returncode == 1
    assert destination.read_bytes() == data
    assert initializer.fingerprint(destination.stat()) == before
    assert DUMMY not in result.stdout + result.stderr
    assert_clean(destination)


def test_fill_missing_preserves_bom_crlf_comments_and_unrelated_values(destination):
    data = (
        initializer.BOM + b"# private synthetic configuration\r\n"
        b"MODEL_API_KEY='" + DUMMY + b"' # do not modify\r\n"
        b"MYSQL_PASSWORD=already-set\n"
        b" export MYSQL_ROOT_PASSWORD = ''  # retain comment\r\n"
        b'MONGO_PASSWORD=""\r\n'
        b"UNKNOWN_VALUE=https://example.invalid/a?x=a=b#fragment\r\n"
        b"REDIS_PASSWORD= \t# empty\r\n"
    )
    write(destination, data)
    result = run(destination, "--fill-missing")
    assert result.returncode == 0
    filled = destination.read_bytes()
    assert re.sub(rb"[a-f0-9]{48}", b"", filled) == data
    assert DUMMY not in result.stdout + result.stderr
    assert filled.count(b"\r\n") == data.count(b"\r\n")
    assert_clean(destination)


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b""])
def test_append_missing_keys_preserves_original_prefix(destination, ending):
    data = b"# comment" + (ending or b"\n") + b"MODEL_API_KEY=" + DUMMY + ending
    write(destination, data)
    assert run(destination, "--fill-missing").returncode == 0
    filled = destination.read_bytes()
    assert filled.startswith(data)
    appended = filled[len(data):]
    assert all(appended.count(key + b"=") == 1 for key in initializer.KEYS)
    if ending == b"\r\n":
        assert b"\n" not in appended.replace(b"\r\n", b"")
    assert_clean(destination)


@pytest.mark.parametrize("empty", [b"", b"   ", b"''", b'""', b" # comment", b"'' # comment"])
def test_clearly_empty_forms_only(destination, empty):
    data = b"MYSQL_PASSWORD=" + empty + b"\n" + b"\n".join(
        key + b"=kept" for key in initializer.KEYS[1:])
    write(destination, data)
    assert run(destination, "--fill-missing").returncode == 0
    assert re.search(rb"[a-f0-9]{48}", destination.read_bytes())
    assert_clean(destination)


def test_nonempty_values_and_idempotency_do_not_write_or_generate(destination, monkeypatch):
    data = b"MYSQL_PASSWORD=' '\nMYSQL_ROOT_PASSWORD=${EXISTING}\nMONGO_PASSWORD=placeholder\nREDIS_PASSWORD=0"
    write(destination, data, 0o400)
    before = initializer.fingerprint(destination.stat())
    monkeypatch.setattr(initializer.secrets, "token_hex", lambda *_: pytest.fail("unexpected credential generation"))
    assert "unchanged" in initializer.initialize(destination, allow_fill=True)
    assert destination.read_bytes() == data
    assert initializer.fingerprint(destination.stat()) == before
    assert_clean(destination)


def test_rerun_after_fill_preserves_every_byte_and_inode(destination):
    write(destination, b"MODEL_API_KEY=" + DUMMY + b"\n")
    assert run(destination, "--fill-missing").returncode == 0
    before_data, before = destination.read_bytes(), initializer.fingerprint(destination.stat())
    assert run(destination, "--fill-missing").returncode == 0
    assert destination.read_bytes() == before_data
    assert initializer.fingerprint(destination.stat()) == before
    assert_clean(destination)


@pytest.mark.parametrize("bad", [
    b"MYSQL_PASSWORD=one\nMYSQL_PASSWORD=two\n",
    b"MODEL_API_KEY=one\nexport MODEL_API_KEY=two\n",
    b"MYSQL_PASSWORD\n", b"MYSQL_PASSWORD: abc\n", b"=value\n",
    b"MYSQL_PASSWORD='unfinished\n", b'MODEL_API_KEY="a\nb"\n',
    b"MYSQL_PASSWORD=''unexpected\n", b"UNKNOWN=trailing\\\n",
    b"UNKNOWN=unquoted'quote\n", b"BAD=\x00\n", b"BAD=\xff\n", b"BAD=value\r",
    b"MYSQL_PASSWORD=\n" + b"#" * (initializer.MAX_BYTES + 1),
])
def test_malformed_and_duplicate_inputs_fail_without_secret_output(destination, bad):
    data = b"# " + DUMMY + b"\n" + bad
    write(destination, data)
    result = run(destination, "--fill-missing")
    assert result.returncode == 1
    assert destination.read_bytes() == data
    assert DUMMY not in result.stdout + result.stderr
    assert b"Traceback" not in result.stderr
    assert_clean(destination)


@pytest.mark.parametrize("mode", [0o400, 0o600, 0o640, 0o644])
def test_permission_bits_never_expand(destination, mode):
    write(destination, b"# synthetic\n", mode)
    assert run(destination, "--fill-missing").returncode == 0
    assert stat.S_IMODE(destination.stat().st_mode) == mode & 0o600
    assert_clean(destination)


@pytest.mark.parametrize("kind", ["symlink", "dangling", "hardlink", "directory", "fifo"])
def test_nonregular_or_linked_destination_is_rejected(destination, kind):
    other = destination.parent / "synthetic-target"
    if kind in {"symlink", "hardlink"}:
        write(other, DUMMY)
    if kind == "symlink":
        destination.symlink_to(other)
    elif kind == "dangling":
        destination.symlink_to(other)
    elif kind == "hardlink":
        os.link(other, destination)
    elif kind == "directory":
        destination.mkdir()
    else:
        os.mkfifo(destination, 0o600)
    result = run(destination, "--fill-missing")
    assert result.returncode == 1
    if other.exists():
        assert other.read_bytes() == DUMMY
    assert DUMMY not in result.stdout + result.stderr
    assert not (destination.parent / ".env.init.lock").exists()
    assert not list(destination.parent.glob(".env.init-*.tmp"))


def test_existing_lock_refuses_without_removing_lock(destination):
    lock = destination.parent / ".env.init.lock"
    write(lock, b"synthetic-lock")
    result = run(destination, "--fill-missing")
    assert result.returncode == 1
    assert not destination.exists()
    assert lock.read_bytes() == b"synthetic-lock"


@pytest.mark.parametrize("stage", ["write", "fsync", "replace"])
def test_failure_is_atomic_redacted_clean_and_retryable(destination, monkeypatch, capsys, stage):
    data = b"MODEL_API_KEY=" + DUMMY + b"\n"
    write(destination, data)

    def fail(*args, **kwargs):
        if stage == "write":
            os.close(args[0])
        raise OSError(DUMMY.decode())

    with monkeypatch.context() as patch:
        if stage == "write":
            patch.setattr(initializer, "write_staged", fail)
        else:
            patch.setattr(initializer.os, stage, fail)
        assert initializer.main(["--path", str(destination), "--fill-missing"]) == 1
    output = capsys.readouterr()
    assert DUMMY.decode() not in output.out + output.err
    assert "Traceback" not in output.err
    assert destination.read_bytes() == data
    assert_clean(destination)
    assert run(destination, "--fill-missing").returncode == 0


@pytest.mark.parametrize("change", ["inplace", "replace", "delete", "symlink", "mode"])
def test_concurrent_changes_detected_before_publication(destination, monkeypatch, change):
    write(destination, b"MODEL_API_KEY=" + DUMMY + b"\n")
    staged_write = initializer.write_staged
    changed = b"# concurrent synthetic writer\n"

    def concurrent(fd, data, mode):
        staged_write(fd, data, mode)
        if change == "inplace":
            destination.write_bytes(changed)
        elif change == "replace":
            replacement = destination.parent / "replacement"
            write(replacement, changed)
            replacement.replace(destination)
        elif change == "delete":
            destination.unlink()
        elif change == "symlink":
            destination.unlink()
            destination.symlink_to("missing-target")
        else:
            destination.chmod(0o400)

    monkeypatch.setattr(initializer, "write_staged", concurrent)
    assert initializer.main(["--path", str(destination), "--fill-missing"]) == 1
    if change in {"inplace", "replace"}:
        assert destination.read_bytes() == changed
    elif change == "delete":
        assert not destination.exists()
    elif change == "symlink":
        assert destination.is_symlink()
    else:
        assert destination.stat().st_mode & 0o777 == 0o400
    assert_clean(destination)


def test_fresh_creation_cannot_overwrite_concurrent_file(destination, monkeypatch):
    staged_write = initializer.write_staged

    def concurrent(fd, data, mode):
        staged_write(fd, data, mode)
        write(destination, DUMMY)

    monkeypatch.setattr(initializer, "write_staged", concurrent)
    assert initializer.main(["--path", str(destination)]) == 1
    assert destination.read_bytes() == DUMMY
    assert_clean(destination)


def test_stage_name_collision_does_not_delete_existing_file(destination, monkeypatch):
    monkeypatch.setattr(initializer.secrets, "token_hex", lambda n: "a" * (2 * n))
    collision = destination.parent / (".env.init-" + "a" * 24 + ".tmp")
    write(collision, DUMMY)
    assert initializer.main(["--path", str(destination)]) == 1
    assert collision.read_bytes() == DUMMY
    assert not destination.exists()
    assert not (destination.parent / ".env.init.lock").exists()


def test_unsafe_destination_directory_rejected(destination):
    destination.parent.chmod(0o777)
    try:
        assert run(destination).returncode == 1
        assert not destination.exists()
    finally:
        destination.parent.chmod(0o700)


def test_explicit_destination_must_be_dotenv(destination):
    assert run(destination.parent / "other-file").returncode == 1
    assert list(destination.parent.iterdir()) == []


def test_native_windows_fails_closed_without_touching_file(destination, monkeypatch):
    write(destination, DUMMY)
    monkeypatch.setattr(initializer, "PLATFORM", "nt")
    with pytest.raises(initializer.UnsafeConfig, match="Native Windows"):
        initializer.initialize(destination, allow_fill=True)
    assert destination.read_bytes() == DUMMY


@pytest.mark.parametrize("allow_fill", [False, True])
def test_windows_fresh_branch_warns_and_preserves_exclusive_creation(destination, monkeypatch, allow_fill):
    monkeypatch.setattr(initializer, "PLATFORM", "nt")
    message = initializer.initialize(destination, allow_fill=allow_fill)
    assert "Windows inherits directory ACLs" in message
    data = destination.read_bytes()
    assert all(re.search(key + rb"=[a-f0-9]{48}\n", data) for key in initializer.KEYS)
    with pytest.raises(initializer.UnsafeConfig):
        initializer.initialize(destination, allow_fill=allow_fill)
    assert destination.read_bytes() == data
    assert_clean(destination)


def test_windows_fresh_failure_cleanup(destination, monkeypatch):
    monkeypatch.setattr(initializer, "PLATFORM", "nt")

    def fail(_fd):
        raise OSError("synthetic failure")

    monkeypatch.setattr(initializer.os, "fsync", fail)
    assert initializer.main(["--path", str(destination)]) == 1
    assert not destination.exists()
    assert_clean(destination)


def test_unspaced_hash_is_a_nonempty_value_not_a_comment(destination):
    data = b"MYSQL_PASSWORD=#keep-this-value\nMODEL_API_KEY=" + DUMMY + b"\n"
    write(destination, data)
    assert run(destination, "--fill-missing").returncode == 0
    assert destination.read_bytes().startswith(data)
    assert_clean(destination)


def test_empty_file_with_opt_in_still_creates_credentials(destination):
    assert run(destination, "--fill-missing").returncode == 0
    assert destination.read_bytes().endswith(b"LAB_PORT=8080\n")
    assert_clean(destination)


def test_unicode_and_escaped_unknown_values_are_preserved(destination):
    data = '# 合成测试，不含真实秘密\r\nMODEL_API_KEY="dummy\\"quoted"\r\n'.encode()
    write(destination, data)
    assert run(destination, "--fill-missing").returncode == 0
    assert destination.read_bytes().startswith(data)
    assert_clean(destination)
