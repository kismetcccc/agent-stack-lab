#!/usr/bin/env bash
# Requires an already built/running core stack. No substitutes for real stores.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'BLOCKED: Docker missing; real integration NOT RUN' >&2; exit 2; }
mkdir -p test-results
chmod 777 test-results # non-root ephemeral test container writes JUnit here
DC=(docker compose -f compose.yaml -f compose.test.yaml)
cleanup() {
  local status=$?
  rm -f test-results/outage-state.json
  # Restore stores and wait for their actual health before replacing Worker.
  # Never remove volumes: this trap also runs on a failed MySQL assertion.
  if docker compose up -d --no-deps --wait --wait-timeout 180 mysql redis mongo kafka >/dev/null; then
    if docker compose up -d --no-deps --force-recreate --wait --wait-timeout 180 worker >/dev/null; then
      printf '%s\n' 'PASS: MySQL/Redis/Mongo/Kafka and Worker restored healthy; volumes retained'
    else
      echo 'FAIL: Worker restoration failed; inspect docker compose ps' >&2
      status=1
    fi
  else
    echo 'FAIL: dependency restoration failed; inspect docker compose ps before restarting Worker' >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
"${DC[@]}" build integration
"${DC[@]}" run --rm --no-deps integration -q /tests/integration/test_chain.py /tests/integration/test_api_contract.py /tests/integration/test_single_agent.py --junitxml=/reports/integration.xml
probe() { "${DC[@]}" run --rm --no-deps --entrypoint python integration /tests/integration/outage_probe.py "$1"; }
# Crash-window/fence tests require exclusive executor ownership.
docker compose stop worker
"${DC[@]}" run --rm --no-deps integration -q /tests/integration/test_recovery.py --junitxml=/reports/recovery.xml
docker compose start worker
# SQL is authoritative even when an already-committed result is cached in Redis.
# Stop Worker before enqueue to observe durable pending+outbox across SQL restart,
# rather than racing a fast deterministic executor. No API restart or DB reset.
probe mysql-prepare
docker compose stop worker
probe mysql-enqueue
docker compose stop mysql
probe mysql-unavailable
docker compose start mysql
probe mysql-restored # bounded readiness wait, original pending/outbox and ownership
docker compose start worker
probe mysql-complete # original outbox -> inbox -> committed result after Worker resumes
# Cache is not task authority.
docker compose stop redis
probe submit
"${DC[@]}" run --rm --no-deps -e EXPECT_REDIS_DOWN=1 --entrypoint python integration /tests/integration/outage_probe.py complete
docker compose start redis
# Kafka outage must leave accepted work in transactional outbox.
docker compose stop kafka
probe submit
probe pending
docker compose start kafka
probe complete
# Existing result: Mongo read outage after explicit Redis cache miss -> 503, not fake data.
probe submit
probe complete-retain
docker compose stop mongo
probe read-unavailable
docker compose start mongo
probe complete
# Mongo must be durable before SQL success; restore before exhausting retry budget.
docker compose stop mongo
probe submit
probe no-success
docker compose start mongo
probe complete
# Stop the executor before enqueue: durable work must survive worker process replacement.
docker compose stop worker
probe submit
probe pending
docker compose up -d --no-deps --force-recreate worker
probe complete
python scripts/test-log-redaction.py
printf '%s\n' 'PASS: real-store chain, duplicate HTTP/Kafka, ownership, CSRF, MySQL/Redis/Kafka/Mongo outages, worker restart'
