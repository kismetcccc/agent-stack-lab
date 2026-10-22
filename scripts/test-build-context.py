#!/usr/bin/env python3
"""Docker-native acceptance of .dockerignore, using only synthetic temporary files.

Run: python scripts/test-build-context.py
Exit 0 = accepted; 1 = failed (including cleanup); 2 = NOT RUN (Docker unavailable).
No project source, real .env, or real .secrets is read or copied. Docker output is
suppressed to avoid disclosing connection/configuration details. No persistent
artifact is written: the synthetic context and exported tar are removed on exit.
The container is created but NEVER started; FROM scratch needs no base download.
"""

import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath

IGNORE_FILE = Path(__file__).resolve().parents[1] / ".dockerignore"
LABEL = "org.agent-stack-lab.build-context-test"
SENTINEL = b"Harmless synthetic build-context sentinel; not a credential.\n"
PRIVATE_PATHS = (
    ".env", ".env.local", ".env.production", ".env.backup.example",
    "config/.env", "config/.env.local", "config/deep/.env.production",
    "config/.env.example", "config/deep/.env.backup.example",
    ".secrets/operations/backup.sql", ".secrets/operations/config.txt",
    "config/.secrets/backup.sql", "config/deep/.secrets/config.txt",
    "private.pem", "private.key", "private.p12", "private.pfx",
    "config/tls/private.pem", "config/tls/private.key",
    "config/tls/private.p12", "config/tls/private.pfx",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "config/ssh/id_rsa", "config/ssh/id_dsa", "config/ssh/id_ecdsa", "config/ssh/id_ed25519",
    "data/backup.sql", "volumes/database/backup.sql",
    *(f"{prefix}local.{kind}{suffix}"
      for prefix in ("", "config/deep/")
      for kind in ("sqlite", "sqlite3", "db")
      for suffix in ("", "-wal", "-shm", "-journal")),
)
# These synthetic paths cover current Dockerfile.api/test/frontend COPY inputs.
# SQL and nested source data stay available; do not blanket-ignore *.sql or **/data.
PUBLIC_PATHS = (
    ".env.example", "pyproject.toml", "uv.lock", "backend/app.py",
    "backend/migrations/001_context_probe.sql", "backend/data/schema.sql",
    "tests/integration/test_chain.py", "frontend/package.json", "frontend/package-lock.json",
    "frontend/src/main.tsx", "infra/nginx/default.conf",
)


class CheckFailed(Exception):
    """A message safe to print without raw subprocess output."""


def create_fixture(ignore_file, context):
    """The public ignore file is the ONLY input copied from the repository."""
    context.mkdir(mode=0o700)
    (context / ".dockerignore").write_bytes(ignore_file.read_bytes())
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /context/\n", encoding="utf-8")
    for relative in PRIVATE_PATHS + PUBLIC_PATHS:
        path = context / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(SENTINEL)


def docker_command(docker, arguments, *, stage, timeout=30, cwd=None):
    """Keep commands bounded and never emit Docker stderr or connection details."""
    try:
        result = subprocess.run(
            [docker, *arguments], cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        raise CheckFailed(f"{stage}: timed out after {timeout}s; operation outcome may be uncertain") from None
    except OSError:
        raise CheckFailed(f"{stage}: Docker could not be executed") from None
    if result.returncode:
        raise CheckFailed(f"{stage}: Docker exited with status {result.returncode}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def verify_archive(archive):
    # Inspect names only; never extract a tar archive into the host filesystem.
    with tarfile.open(archive, "r:") as contents:
        members = {PurePosixPath(item.name).as_posix(): item.isfile() for item in contents}
    leaked = [path for path in PRIVATE_PATHS if f"context/{path}" in members]
    missing = [path for path in PUBLIC_PATHS if not members.get(f"context/{path}")]
    if leaked:
        raise CheckFailed("private synthetic paths survived filtering: " + ", ".join(leaked))
    if missing:
        raise CheckFailed("public synthetic paths were excluded: " + ", ".join(missing))


def cleanup_resource(docker, kind, name, token):
    """Find only this invocation's exact name AND ownership label, then remove its ID.

    Also handles a build/create that succeeded server-side before a client error.
    Query failures are failures, not silently treated as an absent resource.
    """
    arguments = [kind, "ls", "--quiet", "--no-trunc"]
    if kind == "container":
        arguments += ["--all", "--filter", f"name=^/{name}$"]
    else:
        arguments += ["--filter", f"reference={name}"]
    arguments += ["--filter", f"label={LABEL}={token}"]
    stage = f"cleanup {kind} {name}"
    identities = docker_command(docker, arguments, stage=stage).split()
    if not identities:
        return
    if len(identities) != 1 or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", identities[0]):
        raise CheckFailed(f"{stage}: could not establish exact owned identity; nothing removed")
    arguments = [kind, "rm"]
    if kind == "image":
        arguments.append("--no-prune")
    docker_command(docker, [*arguments, identities[0]], stage=stage)


def check_context(docker, ignore_file=IGNORE_FILE):
    token = uuid.uuid4().hex
    name = f"agent-stack-build-context-{token}"
    image = f"{name}:test"
    errors = []
    build_attempted = create_attempted = False
    with tempfile.TemporaryDirectory(prefix="agent-stack-build-context-") as temporary:
        root = Path(temporary)  # TemporaryDirectory is private (0700).
        context = root / "context"
        archive = root / "filesystem.tar"  # Outside the context; cannot copy itself.
        create_fixture(ignore_file, context)
        try:
            build_attempted = True
            docker_command(docker, [
                "build", "--pull=false", "--network=none", "--no-cache",
                "--label", f"{LABEL}={token}", "--tag", image, ".",
            ], stage=f"synthetic image build {image}", timeout=120, cwd=context)
            create_attempted = True
            docker_command(docker, [
                "container", "create", "--pull=never", "--network=none", "--name", name,
                "--label", f"{LABEL}={token}", image, "/__never_executed__",
            ], stage=f"unstarted synthetic container creation {name}")
            docker_command(docker, [
                "container", "export", "--output", str(archive), name,
            ], stage="synthetic filesystem export")
            verify_archive(archive)
        except CheckFailed as error:
            errors.append(str(error))
        except KeyboardInterrupt:
            errors.append(f"interrupted; Docker outcome may be uncertain for {name}")
        except (OSError, tarfile.TarError):
            errors.append("synthetic filesystem archive could not be inspected")
        finally:
            for attempted, kind, identity in (
                (create_attempted, "container", name), (build_attempted, "image", image),
            ):
                if attempted:
                    try:
                        cleanup_resource(docker, kind, identity, token)
                    except CheckFailed as error:
                        errors.append(str(error))
        if errors:
            raise CheckFailed("; ".join(errors))


def main():
    docker = shutil.which("docker")
    if docker is None:
        print("NOT RUN: Docker CLI unavailable; real context filtering was not tested.", file=sys.stderr)
        return 2
    try:
        docker_command(docker, ["version", "--format", "{{.Server.Version}}"],
                       stage="Docker availability", timeout=15)
    except CheckFailed:
        print("NOT RUN: Docker daemon unavailable; real context filtering was not tested.", file=sys.stderr)
        return 2
    try:
        check_context(docker)
    except CheckFailed as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("FAIL: synthetic temporary files could not be prepared or cleaned up.", file=sys.stderr)
        return 1
    print(f"PASS: Docker excluded {len(PRIVATE_PATHS)} private synthetic paths and kept "
          f"{len(PUBLIC_PATHS)} public paths; temporary container/image removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
