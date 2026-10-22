#!/usr/bin/env python3
"""Redact generated environment secrets and credentials before publishing CI logs."""
import re
import sys
from pathlib import Path

text = sys.stdin.read()
env = Path('.env')
if env.exists():
    for line in env.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            if any(part in key for part in ('PASSWORD', 'TOKEN', 'SECRET', 'KEY')) and value:
                text = text.replace(value, '[REDACTED]')
text = re.sub(r'(://[^:\s/@]+:)[^@\s]+(@)', r'\1[REDACTED]\2', text)
text = re.sub(r'(?i)(authorization[\"\s:]+(?:bearer )?)[^\s,\"]+', r'\1[REDACTED]', text)
sys.stdout.write(text)
