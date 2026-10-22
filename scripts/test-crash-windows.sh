#!/usr/bin/env bash
# Isolated real SIGKILL experiments. Requires running core and the prebuilt integration image.
# Deterministic only; no volume deletion, offset reset, lease mutation or live provider call.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'BLOCKED: Docker missing; crash windows NOT RUN' >&2; exit 2; }
mkdir -p test-results
chmod 777 test-results # ephemeral non-root integration container writes reports here
DC=(docker compose -f compose.yaml -f compose.test.yaml)
point=''
probe() {
  "${DC[@]}" run --rm --no-deps -e PYTHONPATH=/app -e TEST_HOOK_POINT="$point" \
    -e TEST_HOOK_MARKER="${marker:-}" -e TEST_KILL_VERIFIED="${kill_verified:-0}" \
    -e TEST_CLEANUP_OK="${cleanup_ok:-0}" -e TEST_RUN_FAILED="${run_failed:-0}" \
    --entrypoint python integration /tests/integration/crash_probe.py "$1"
}
restore_worker() {
  docker compose up -d --no-deps --force-recreate --wait --wait-timeout 180 worker >/dev/null 2>&1 &&
    docker compose exec -T worker python -c '
import os
from pathlib import Path
assert os.getenv("LAB_MODE") == "production" and os.getenv("MODEL_MODE") == "deterministic"
assert all(not os.getenv(name) for name in ("LAB_TEST_HOOKS", "LAB_TEST_PAUSE_AT", "LAB_TEST_TASK_ID", "LAB_TEST_RUN_ID"))
assert not list(Path("/tmp").glob("lab-hook-*.json"))
' >/dev/null 2>&1
}
cleanup() {
  local status=$?
  trap - EXIT
  cleanup_ok=0
  run_failed=0
  if restore_worker; then
    cleanup_ok=1
  else
    echo 'FAIL: hook-free Worker restoration failed; inspect Compose health' >&2
    status=1
  fi
  if [[ "$status" != 0 ]]; then run_failed=1; fi
  # The container owner removes its own 0600 private state; reports contain only an allowlist.
  if ! probe cleanup; then
    echo 'FAIL: private state/report cleanup failed' >&2
    status=1
    # Do not silently leave cookies behind if the probe container could not run.
    if ! rm -f test-results/crash-state.json; then
      echo 'FAIL: remove private test-results/crash-state.json before sharing artifacts' >&2
    fi
  fi
  if [[ "$status" == 0 ]]; then
    echo 'PASS: 4 real SIGKILL windows, replay/dedup/attempt isolation and hook-free cleanup; not pytest counts'
  fi
  exit "$status"
}
trap cleanup EXIT
probe init
for point in after_outbox_publish after_inbox_commit after_claim after_mongo_save; do
  docker compose stop worker >/dev/null 2>&1
  probe prepare
  identity="$(probe identity)"
  read -r target run_id <<< "$identity"
  LAB_TEST_PAUSE_AT="$point" LAB_TEST_TASK_ID="$target" LAB_TEST_RUN_ID="$run_id" \
    docker compose -f compose.yaml -f compose.fault-test.yaml up -d --no-deps --force-recreate worker \
      >/dev/null 2>&1
  marker=''
  for _ in $(seq 1 60); do
    # This checks point/task/run, expiry and Linux process start identity, not just file existence.
    if marker="$(docker compose exec -T worker python -c '
import json, sys
from backend.faults import read_marker
try:
    print(json.dumps(read_marker(*sys.argv[1:])))
except Exception:
    raise SystemExit(1) from None
' "$point" "$target" "$run_id" 2>/dev/null)"; then break; fi
    sleep 1
  done
  [[ -n "$marker" ]] || { echo "FAIL: target hook not reached: $point" >&2; exit 1; }
  probe boundary
  # Recheck immediately before kill so a timeout/normal resume cannot masquerade as a paused crash.
  docker compose exec -T worker python -c '
import sys, time
from backend.faults import read_marker
try:
    marker = read_marker(*sys.argv[1:])
    assert marker["expires_at"] - time.time() > 10
except Exception:
    raise SystemExit(1) from None
' "$point" "$target" "$run_id" >/dev/null 2>&1
  container="$(docker compose ps -q worker)"
  [[ -n "$container" ]]
  docker compose kill -s SIGKILL worker >/dev/null 2>&1
  [[ "$(docker inspect --format '{{.State.ExitCode}} {{.State.Running}}' "$container")" == '137 false' ]] || {
    echo 'FAIL: Worker SIGKILL exit was not observed' >&2; exit 1;
  }
  kill_verified=1
  probe killed # Recheck the durable boundary while Worker is still stopped, not only the exit code.
  restore_worker || { echo 'FAIL: hook-free recovery Worker did not become healthy' >&2; exit 1; }
  probe recover
  kill_verified=0
done
