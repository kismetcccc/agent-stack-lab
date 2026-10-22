#!/usr/bin/env python3
"""Create private development credentials; never overwrite existing credentials."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env'
keys = ['MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD', 'MONGO_PASSWORD', 'REDIS_PASSWORD']
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('.env exists; preserving it. Remove it explicitly only if resetting credentials and data.')
with os.fdopen(fd, 'w') as stream:
    stream.write('# Generated locally. Never commit this file. Password rotation requires datastore changes.\n')
    for key in keys:
        stream.write(f'{key}={secrets.token_hex(24)}\n')
    stream.write('LAB_PORT=8080\n')
print('Created private .env with random credentials (values not printed).')
