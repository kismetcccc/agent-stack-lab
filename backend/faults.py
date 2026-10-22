"""Opt-in, task-scoped crash-lab hooks. No HTTP switch; ordinary execution is a no-op."""

import json
import os
import re
import time
import uuid
from pathlib import Path

POINTS = frozenset({"after_inbox_commit", "after_mongo_save", "after_claim", "after_outbox_publish"})
PAUSE_SECONDS = 90
MARKER_DIR = Path("/tmp")


def valid_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def marker_path(point, run_id):
    if point not in POINTS or not valid_id(run_id):
        raise ValueError("invalid fault marker identity")
    return MARKER_DIR / f"lab-hook-{point}-{run_id}.json"


def process_start(pid):
    # Linux /proc start ticks distinguish a live Worker from a later reused PID.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    if fields[0] in {"Z", "X"}:
        raise ValueError("fault marker process is no longer alive")
    return fields[19]


def read_marker(point, task_id, run_id):
    """Host probe must check identity, lifetime AND the still-live originating process."""
    marker = json.loads(marker_path(point, run_id).read_text())
    if (
        marker["version"] != 1
        or marker["point"] != point
        or marker["task_id"] != task_id
        or marker["run_id"] != run_id
        or not marker["created_at"] <= time.time() < marker["expires_at"]
        or marker["expires_at"] - marker["created_at"] != PAUSE_SECONDS
        or type(marker["pid"]) is not int
        or marker["pid"] <= 0
        or process_start(marker["pid"]) != marker["process_start"]
    ):
        raise ValueError("stale or mismatched fault marker")
    return marker


def pause_at(
    point,
    task_id=None,
    *,
    event_id=None,
    attempt_id=None,
    fence=None,
    topic=None,
    partition=None,
    offset=None,
):
    if os.getenv("LAB_TEST_HOOKS") != "true":
        return
    if point not in POINTS:
        raise ValueError("unknown fault point")
    if os.getenv("LAB_TEST_PAUSE_AT") != point:
        return
    target, run_id = os.getenv("LAB_TEST_TASK_ID"), os.getenv("LAB_TEST_RUN_ID")
    if not valid_id(task_id) or task_id != target or not valid_id(run_id):
        return  # Missing/wrong targets cannot pause an unrelated task.
    metadata = {}
    if point in {"after_outbox_publish", "after_inbox_commit"}:
        if not valid_id(event_id):
            raise ValueError("fault hook requires event identity")
        metadata["event_id"] = event_id
    else:
        if not valid_id(attempt_id) or type(fence) is not int or fence < 1:
            raise ValueError("fault hook requires attempt identity")
        metadata.update(attempt_id=attempt_id, fence=fence)
    if point == "after_inbox_commit":
        if (
            not isinstance(topic, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,249}", topic)
            or type(partition) is not int
            or partition < 0
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError("fault hook requires Kafka position")
        metadata.update(topic=topic, partition=partition, offset=offset)
    created = time.time()
    marker = dict(
        version=1,
        point=point,
        task_id=task_id,
        run_id=run_id,
        pid=os.getpid(),
        process_start=process_start(os.getpid()),
        created_at=created,
        expires_at=created + PAUSE_SECONDS,
        **metadata,
    )
    path = marker_path(point, run_id)
    # Unique run identity + exclusive creation: an old file can never be accepted as a new pause.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(marker, handle)
        time.sleep(PAUSE_SECONDS)
    finally:
        path.unlink(missing_ok=True)  # SIGKILL cannot run finally; forced container replacement removes /tmp.
