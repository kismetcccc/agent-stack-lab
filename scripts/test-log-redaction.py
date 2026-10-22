#!/usr/bin/env python3
"""Read logs in memory only; fail without printing secrets or raw log contents."""

import re
import subprocess
from pathlib import Path

logs = subprocess.run(
    ["docker", "compose", "logs", "--no-color", "api", "worker"], capture_output=True, text=True, check=True
).stdout
secrets = [
    "Test-only!42-password",
    "Other-only!password42",
    "Browser-only!42-password",
    "Integration-only!42-",
]
for line in Path(".env").read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        if any(term in key for term in ("PASSWORD", "SECRET", "API_KEY")) and len(value.strip()) > 5:
            secrets.append(value.strip().strip("\"'"))
assert not any(secret in logs for secret in secrets), (
    "FAIL: credential marker found in API/worker logs (value withheld)"
)
assert not re.search(
    r"(Bearer\s+[A-Za-z0-9._-]{12,}|lab_session=[A-Za-z0-9_-]{12,}|mysql\+pymysql://[^\s]+@)", logs
), "FAIL: sensitive token/DSN found in logs (value withheld)"
print(
    "PASS: API/worker log scan found no tested credential/token/DSN patterns; not a general proof of absence"
)
