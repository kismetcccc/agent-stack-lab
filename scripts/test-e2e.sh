#!/usr/bin/env bash
# Backend must be the running four-store production stack; only model is deterministic.
set -euo pipefail
cd "$(dirname "$0")/../tests/e2e"
export npm_config_cache="${npm_config_cache:-/tmp/agent-stack-npm-cache}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/tmp/agent-stack-playwright}"
export TEST_BASE_URL="${TEST_BASE_URL:-http://localhost:8081}"
npm ci --no-audit
if [[ "${CI:-}" == "true" ]]; then
  npx playwright install --with-deps chromium
else
  npx playwright install chromium
fi
npm test
