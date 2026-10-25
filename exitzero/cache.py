from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from .config import CACHE_PATH, CACHE_TTL, CACHE_MAX_ENTRIES, SCHEMA_VERSION
from .models import Diagnosis

def _is_disabled() -> bool:
    """Check at call time so tests can set/unset EXITZERO_CACHE_DISABLED freely."""
    return os.environ.get("EXITZERO_CACHE_DISABLED", "0").strip() == "1"


def _key(normalized_window: str) -> str:
    return hashlib.sha256(normalized_window.encode()).hexdigest()


def _load(path: Path) -> dict:
    try:
        with path.open("r") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".exitzero_cache_")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        Path(tmp).replace(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _evict(data: dict) -> dict:
    now = time.time()
    clean = {
        k: v for k, v in data.items()
        if isinstance(v, dict)
        and isinstance(v.get("stored_at"), (int, float))
        and now - v["stored_at"] < CACHE_TTL
        and v.get("schema_version") == SCHEMA_VERSION
    }
    if len(clean) > CACHE_MAX_ENTRIES:
        sorted_keys = sorted(clean, key=lambda k: clean[k].get("stored_at", 0))
        for old in sorted_keys[: len(clean) - CACHE_MAX_ENTRIES]:
            del clean[old]
    return clean


def get(normalized_window: str, path: Path = CACHE_PATH) -> Optional[Diagnosis]:
    if _is_disabled():
        return None
    data = _load(path)
    k = _key(normalized_window)
    entry = data.get(k)
    if not isinstance(entry, dict):
        return None
    if entry.get("schema_version") != SCHEMA_VERSION:
        return None
    stored_at = entry.get("stored_at", 0)
    if not isinstance(stored_at, (int, float)) or time.time() - stored_at >= CACHE_TTL:
        return None
    try:
        diag = Diagnosis.from_dict(entry["diagnosis"])
        diag.cache_hit = True
        return diag
    except (KeyError, ValueError):
        return None


def set(normalized_window: str, diagnosis: Diagnosis, path: Path = CACHE_PATH) -> None:  # noqa: A001
    if _is_disabled():
        return
    data = _load(path)
    k = _key(normalized_window)
    data[k] = {
        "schema_version": SCHEMA_VERSION,
        "stored_at": time.time(),
        "diagnosis": diagnosis.to_dict(),
    }
    data = _evict(data)
    _save(path, data)


def invalidate(normalized_window: str, path: Path = CACHE_PATH) -> bool:
    data = _load(path)
    k = _key(normalized_window)
    if k not in data:
        return False
    del data[k]
    _save(path, data)
    return True


def clear(path: Path = CACHE_PATH) -> int:
    data = _load(path)
    count = len(data)
    _save(path, {})
    return count


def stats(path: Path = CACHE_PATH) -> dict:
    data = _load(path)
    now = time.time()
    total = len(data)
    expired = sum(
        1 for v in data.values()
        if isinstance(v, dict) and now - v.get("stored_at", 0) >= CACHE_TTL
    )
    schema_mismatch = sum(
        1 for v in data.values()
        if isinstance(v, dict) and v.get("schema_version") != SCHEMA_VERSION
    )
    return {
        "total": total,
        "valid": total - expired - schema_mismatch,
        "expired": expired,
        "schema_mismatch": schema_mismatch,
    }
