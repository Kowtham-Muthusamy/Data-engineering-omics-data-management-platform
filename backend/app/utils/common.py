import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
VERSION_RE = re.compile(r"^V\d+$")


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no tz support; the API serialises it as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_bytes(path, json.dumps(obj, indent=2, sort_keys=True).encode("utf-8"))


def safe_join(base: Path, rel: str) -> Path:
    """Join ``rel`` under ``base`` and refuse anything that escapes it."""
    base = base.resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"path escapes base directory: {rel}")
    return target
