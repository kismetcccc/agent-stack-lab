#!/usr/bin/env python3
"""Create development credentials, or explicitly fill empty entries without rotation.

Existing-file updates require local POSIX filesystems. Stop other writers first:
the exclusive lock coordinates this helper, not arbitrary programs ignoring it.
Native Windows retains exclusive fresh creation, with inherited ACLs only.
"""

import argparse
import os
import re
import secrets
import stat
import sys
from pathlib import Path

KEYS = (b"MYSQL_PASSWORD", b"MYSQL_ROOT_PASSWORD", b"MONGO_PASSWORD", b"REDIS_PASSWORD")
PLATFORM = os.name
MAX_BYTES = 1024 * 1024
BOM = b"\xef\xbb\xbf"
ASSIGNMENT = re.compile(rb"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=([ \t]*)(.*)")
HEADER = b"# Generated locally. Never commit this file. Password rotation requires datastore changes.\n"


class UnsafeConfig(Exception):
    """Only fixed, non-secret messages may be exposed to the CLI."""


def fill_missing(data):
    """Validate a conservative single-line dotenv subset and patch bytes only."""
    try:
        data.decode("utf-8-sig")
    except UnicodeError:
        raise UnsafeConfig("Unsupported encoding; expected UTF-8, optionally with a BOM.") from None
    if len(data) > MAX_BYTES or re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\r(?!\n)", data):
        raise UnsafeConfig("Unsupported size, control character or newline format.")
    bom = BOM if data.startswith(BOM) else b""
    lines = data[len(bom):].splitlines(keepends=True)
    seen, patches = set(), []
    for index, line in enumerate(lines):
        body = line[:-2] if line.endswith(b"\r\n") else line.removesuffix(b"\n")
        if not body.strip(b" \t") or body.lstrip(b" \t").startswith(b"#"):
            continue
        match = ASSIGNMENT.fullmatch(body)
        if not match:
            raise UnsafeConfig("Unsupported dotenv syntax; use single-line KEY=value entries.")
        key, _, value = match.groups()
        if key in seen:
            raise UnsafeConfig("Duplicate dotenv keys are ambiguous; no credentials were changed.")
        seen.add(key)
        insertion = None
        if value.startswith((b"'", b'"')):
            quote, end = value[:1], 1
            while end < len(value):
                if value[end:end + 1] == b"\\":
                    end += 2
                    continue
                if value[end:end + 1] == quote:
                    break
                end += 1
            if end >= len(value) or not re.fullmatch(rb"[ \t]*(?:#.*)?", value[end + 1:]):
                raise UnsafeConfig("Unsupported quoted or multiline dotenv value.")
            if end == 1:
                insertion = match.start(3) + 1
        else:
            # An inline unquoted comment starts at '#' only after whitespace.
            content = re.split(rb"[ \t]+#", value, maxsplit=1)[0].rstrip(b" \t")
            if value.startswith(b"#") and match[2]:
                content = b""
            if b"'" in content or b'"' in content or content.endswith(b"\\"):
                raise UnsafeConfig("Unsupported unquoted dotenv value; use one quoted line.")
            if not content:
                # Insert before existing whitespace, keeping comments and spacing intact.
                insertion = match.start(2)
        if key in KEYS and insertion is not None:
            patches.append((index, insertion))
    missing = [key for key in KEYS if key not in seen]
    for index, offset in patches:
        line = lines[index]
        lines[index] = line[:offset] + secrets.token_hex(24).encode("ascii") + line[offset:]
    result = bom + b"".join(lines)
    if missing:
        first_newline = re.search(rb"\r?\n", data)
        newline = first_newline[0] if first_newline else b"\n"
        if result and result != bom and not result.endswith(b"\n"):
            result += newline
        result += b"".join(key + b"=" + secrets.token_hex(24).encode("ascii") + newline for key in missing)
    return result, len(patches) + len(missing)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def regular_private_owner(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        raise UnsafeConfig("Destination must be a regular, singly linked file owned by the current user.")


def snapshot(directory, name):
    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    regular_private_owner(info)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        if fingerprint(os.fstat(stream.fileno())) != fingerprint(info):
            raise UnsafeConfig("Destination changed concurrently; retry only after other writers stop.")
        data = stream.read(MAX_BYTES + 1)
        if fingerprint(os.fstat(stream.fileno())) != fingerprint(info):
            raise UnsafeConfig("Destination changed concurrently; retry only after other writers stop.")
    if len(data) > MAX_BYTES:
        raise UnsafeConfig("Destination exceeds the supported size limit.")
    return data, info


def verify_unchanged(directory, name, data, info):
    current, current_info = snapshot(directory, name)
    if current != data or fingerprint(current_info) != fingerprint(info):
        raise UnsafeConfig("Destination changed concurrently; no replacement was made.")


def write_staged(fd, data, mode):
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        # Strip group/other and special bits, never add an owner's permission.
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())


def windows_fresh(path, *, allow_fill):
    """Legacy exclusive creation only; do not replace files or alter Windows ACLs."""
    if os.path.lexists(path):
        if allow_fill:
            raise UnsafeConfig("Native Windows existing-file fill is unsupported; preserve it and configure manually.")
        raise UnsafeConfig(".env exists; preserved unchanged.")
    result, count = fill_missing(HEADER)
    result += b"LAB_PORT=8080\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    identity = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Only remove our own failed fresh file, never an observed replacement.
        current = path.lstat()
        if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            path.unlink()
        raise
    return (f"Created {count} development credentials (values not printed). "
            "Warning: Windows inherits directory ACLs; 0600 is not an ACL guarantee. Use a private directory.")


def initialize(path, *, allow_fill=False):
    path = Path(path)
    if path.name != ".env":
        raise UnsafeConfig("The explicit destination must be named .env in an existing private directory.")
    if PLATFORM == "nt":
        return windows_fresh(path, allow_fill=allow_fill)
    if PLATFORM != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise UnsafeConfig("Unsupported filesystem APIs: use a private Linux filesystem instead.")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock, staged = False, None
    try:
        parent = os.fstat(directory)
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o022:
            raise UnsafeConfig("Destination directory must be user-owned and not writable by group or others.")
        try:
            lock_fd = os.open(".env.init.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=directory)
        except FileExistsError:
            raise UnsafeConfig("Initialization lock exists; stop other writers and investigate before retrying.") from None
        lock = True
        os.close(lock_fd)
        try:
            os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            original, info = None, None
        else:
            if not allow_fill:
                raise UnsafeConfig(".env exists; preserved unchanged. Use --fill-missing only to add empty credentials.")
            original, info = snapshot(directory, path.name)
        if original is None:
            result, count = fill_missing(HEADER)
            result += b"LAB_PORT=8080\n"
        else:
            result, count = fill_missing(original)
            if not count:
                verify_unchanged(directory, path.name, original, info)
                return "No missing credentials; .env unchanged."
        candidate = ".env.init-" + secrets.token_hex(12) + ".tmp"
        fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        staged = candidate
        write_staged(fd, result, stat.S_IMODE(info.st_mode) & 0o600 if info else 0o600)
        if info:
            verify_unchanged(directory, path.name, original, info)
            os.replace(staged, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            staged = None
        else:
            # Atomic publication without overwrite if another program created .env.
            os.link(staged, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        return f"{'Filled' if info else 'Created'} {count} development credentials (values not printed)."
    finally:
        try:
            if staged is not None:
                os.unlink(staged, dir_fd=directory)
        finally:
            try:
                if lock:
                    os.unlink(".env.init.lock", dir_fd=directory)
            finally:
                os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fill-missing", action="store_true",
                        help="fill absent/empty credentials only for fresh, uninitialized datastores")
    parser.add_argument("--path", type=Path, default=Path(__file__).resolve().parents[1] / ".env",
                        help="explicit .env destination in an existing private directory (default: project .env)")
    args = parser.parse_args(argv)
    try:
        message = initialize(args.path, allow_fill=args.fill_missing)
    except UnsafeConfig as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        # Never print OS exception text: filenames or mocked errors may contain secrets.
        print("Initialization failed safely; inspect destination permissions, locks and concurrent writers.", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
