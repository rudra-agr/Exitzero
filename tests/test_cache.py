from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from exitzero.models import (
    Category, Confidence, Diagnosis, Evidence, Language, Source,
    VerificationStatus,
)
from exitzero import cache as cache_mod
from exitzero.config import SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_diag(**kwargs) -> Diagnosis:
    defaults = dict(
        category=Category.DEPENDENCY_ERROR,
        confidence=Confidence.HIGH,
        plain_english="missing module",
        fix_explanation="pip install it",
        evidence=[Evidence(source="read_file:foo.py", fact="import missing", observed=True)],
        language=Language.PYTHON,
    )
    defaults.update(kwargs)
    return Diagnosis(**defaults)


@pytest.fixture
def cache_path(tmp_path) -> Path:
    return tmp_path / "test_cache.json"


# ---------------------------------------------------------------------------
# get / set roundtrip
# ---------------------------------------------------------------------------

def test_get_miss_on_empty_cache(cache_path):
    assert cache_mod.get("any window", path=cache_path) is None


def test_set_then_get_roundtrip(cache_path):
    diag = _make_diag()
    cache_mod.set("window_a", diag, path=cache_path)
    result = cache_mod.get("window_a", path=cache_path)
    assert result is not None
    assert result.plain_english == diag.plain_english
    assert result.category == diag.category
    assert result.confidence == diag.confidence
    assert result.language == diag.language


def test_different_windows_are_independent(cache_path):
    diag_a = _make_diag(plain_english="error A")
    diag_b = _make_diag(plain_english="error B")
    cache_mod.set("window_a", diag_a, path=cache_path)
    cache_mod.set("window_b", diag_b, path=cache_path)
    assert cache_mod.get("window_a", path=cache_path).plain_english == "error A"
    assert cache_mod.get("window_b", path=cache_path).plain_english == "error B"


def test_overwrite_same_window(cache_path):
    cache_mod.set("window_x", _make_diag(plain_english="first"), path=cache_path)
    cache_mod.set("window_x", _make_diag(plain_english="second"), path=cache_path)
    assert cache_mod.get("window_x", path=cache_path).plain_english == "second"


def test_cache_hit_flag_set_on_return(cache_path):
    cache_mod.set("window_flag", _make_diag(), path=cache_path)
    result = cache_mod.get("window_flag", path=cache_path)
    assert result.cache_hit is True


def test_evidence_roundtrip(cache_path):
    evidence = [
        Evidence(source="read_file:main.py", fact="line 42", observed=True),
        Evidence(source="search_codebase:foo", fact="defined here", observed=False),
    ]
    diag = _make_diag(evidence=evidence)
    cache_mod.set("window_ev", diag, path=cache_path)
    result = cache_mod.get("window_ev", path=cache_path)
    assert len(result.evidence) == 2
    assert result.evidence[0].source == "read_file:main.py"
    assert result.evidence[1].observed is False


def test_patch_diff_preserved(cache_path):
    diag = _make_diag(patch_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y")
    cache_mod.set("window_patch", diag, path=cache_path)
    result = cache_mod.get("window_patch", path=cache_path)
    assert result.patch_diff is not None
    assert "@@" in result.patch_diff


def test_cache_hit_not_serialized(cache_path):
    cache_mod.set("window_s", _make_diag(), path=cache_path)
    raw = json.loads(cache_path.read_text())
    key = list(raw.keys())[0]
    assert "cache_hit" not in raw[key]["diagnosis"]


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------

def test_expired_entry_returns_none(cache_path, monkeypatch):
    cache_mod.set("window_ttl", _make_diag(), path=cache_path)
    # Wind time forward past TTL using a fixed future timestamp
    future = time.time() + 999_999
    monkeypatch.setattr(cache_mod.time, "time", lambda: future)
    assert cache_mod.get("window_ttl", path=cache_path) is None


def test_non_expired_entry_returns_hit(cache_path):
    cache_mod.set("window_fresh", _make_diag(), path=cache_path)
    result = cache_mod.get("window_fresh", path=cache_path)
    assert result is not None


# ---------------------------------------------------------------------------
# Schema version guard
# ---------------------------------------------------------------------------

def test_schema_mismatch_returns_none(cache_path):
    cache_mod.set("window_schema", _make_diag(), path=cache_path)
    # Corrupt the schema_version in the file
    raw = json.loads(cache_path.read_text())
    key = list(raw.keys())[0]
    raw[key]["schema_version"] = SCHEMA_VERSION + 99
    cache_path.write_text(json.dumps(raw))
    assert cache_mod.get("window_schema", path=cache_path) is None


def test_schema_mismatch_evicted_on_next_set(cache_path):
    cache_mod.set("window_old", _make_diag(), path=cache_path)
    raw = json.loads(cache_path.read_text())
    key = list(raw.keys())[0]
    raw[key]["schema_version"] = 0
    cache_path.write_text(json.dumps(raw))
    # Adding a new entry should evict the stale one
    cache_mod.set("window_new", _make_diag(), path=cache_path)
    raw2 = json.loads(cache_path.read_text())
    assert all(v.get("schema_version") == SCHEMA_VERSION for v in raw2.values())


# ---------------------------------------------------------------------------
# Max entries eviction
# ---------------------------------------------------------------------------

def test_max_entries_evicts_oldest(cache_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_MAX_ENTRIES", 3)
    base_time = time.time()
    for i in range(4):
        monkeypatch.setattr(cache_mod.time, "time", lambda t=base_time + i: t)
        cache_mod.set(f"window_{i}", _make_diag(plain_english=f"error {i}"), path=cache_path)

    # oldest (window_0) should be gone
    assert cache_mod.get("window_0", path=cache_path) is None
    # newest three should survive
    assert cache_mod.get("window_1", path=cache_path) is not None
    assert cache_mod.get("window_2", path=cache_path) is not None
    assert cache_mod.get("window_3", path=cache_path) is not None


def test_at_max_entries_no_eviction(cache_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_MAX_ENTRIES", 3)
    for i in range(3):
        cache_mod.set(f"window_{i}", _make_diag(), path=cache_path)
    raw = json.loads(cache_path.read_text())
    assert len(raw) == 3


# ---------------------------------------------------------------------------
# Atomic write — file is valid JSON even if another process reads mid-write
# ---------------------------------------------------------------------------

def test_file_is_valid_json_after_set(cache_path):
    cache_mod.set("window_atomic", _make_diag(), path=cache_path)
    assert json.loads(cache_path.read_text())  # would raise if malformed


def test_corrupt_cache_file_returns_none(cache_path):
    cache_path.write_text("not json at all {{")
    assert cache_mod.get("any", path=cache_path) is None


def test_missing_cache_file_returns_none(tmp_path):
    missing = tmp_path / "nonexistent.json"
    assert cache_mod.get("any", path=missing) is None


# ---------------------------------------------------------------------------
# invalidate / clear / stats
# ---------------------------------------------------------------------------

def test_invalidate_existing_key(cache_path):
    cache_mod.set("window_inv", _make_diag(), path=cache_path)
    removed = cache_mod.invalidate("window_inv", path=cache_path)
    assert removed is True
    assert cache_mod.get("window_inv", path=cache_path) is None


def test_invalidate_missing_key(cache_path):
    assert cache_mod.invalidate("not_there", path=cache_path) is False


def test_clear_removes_all(cache_path):
    for i in range(5):
        cache_mod.set(f"w{i}", _make_diag(), path=cache_path)
    count = cache_mod.clear(path=cache_path)
    assert count == 5
    assert json.loads(cache_path.read_text()) == {}


def test_stats_valid_count(cache_path):
    cache_mod.set("w1", _make_diag(), path=cache_path)
    cache_mod.set("w2", _make_diag(), path=cache_path)
    s = cache_mod.stats(path=cache_path)
    assert s["total"] == 2
    assert s["valid"] == 2
    assert s["expired"] == 0
    assert s["schema_mismatch"] == 0


def test_stats_expired_count(cache_path, monkeypatch):
    cache_mod.set("w_exp", _make_diag(), path=cache_path)
    cache_mod.set("w_fresh", _make_diag(), path=cache_path)
    # Force one to appear expired by backdating stored_at
    raw = json.loads(cache_path.read_text())
    keys = list(raw.keys())
    raw[keys[0]]["stored_at"] = 0
    cache_path.write_text(json.dumps(raw))
    s = cache_mod.stats(path=cache_path)
    assert s["expired"] == 1
    assert s["valid"] == 1


def test_stats_schema_mismatch_count(cache_path):
    cache_mod.set("w_bad", _make_diag(), path=cache_path)
    raw = json.loads(cache_path.read_text())
    key = list(raw.keys())[0]
    raw[key]["schema_version"] = 0
    cache_path.write_text(json.dumps(raw))
    s = cache_mod.stats(path=cache_path)
    assert s["schema_mismatch"] == 1
