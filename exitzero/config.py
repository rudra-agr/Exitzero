from __future__ import annotations

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv


def _find_env() -> str | None:
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return str(candidate)
    pkg_env = Path(__file__).parent.parent / ".env"
    if pkg_env.is_file():
        return str(pkg_env)
    return None


_env_path = _find_env()
if _env_path:
    load_dotenv(dotenv_path=_env_path, override=False)


def _path(env_key: str, default: Path) -> Path:
    raw = os.environ.get(env_key, "")
    return Path(raw).expanduser() if raw else default


# ---------------------------------------------------------------------------
# LLM backend — "ollama" or "openrouter"
# ---------------------------------------------------------------------------

LLM_BACKEND = os.environ.get("EXITZERO_LLM_BACKEND", "openrouter").lower()

# OpenRouter settings
_raw_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_API_KEY = "" if _raw_key in ("", "your_key_here", "sk-or-...") else _raw_key
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Default free models on OpenRouter (no payment required)
PRIMARY_MODEL = os.environ.get(
    "EXITZERO_PRIMARY_MODEL",
    "meta-llama/llama-3.1-8b-instruct:free",
)
BACKUP_MODEL = os.environ.get(
    "EXITZERO_BACKUP_MODEL",
    "google/gemma-2-9b-it:free",
)

if LLM_BACKEND == "ollama":
    OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

LLM_TEMPERATURE = 0.0
LLM_TIMEOUT     = int(os.environ.get("EXITZERO_LLM_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_PATH        = _path("EXITZERO_CACHE_PATH",  Path.home() / ".exitzero_cache.json")
CACHE_TTL         = int(os.environ.get("EXITZERO_CACHE_TTL", str(7 * 24 * 60 * 60)))
CACHE_MAX_ENTRIES = int(os.environ.get("EXITZERO_CACHE_MAX_ENTRIES", "500"))

# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

HISTORY_PATH      = _path("EXITZERO_HISTORY_PATH", Path.home() / ".exitzero_history.jsonl")
HISTORY_MAX_LINES = int(os.environ.get("EXITZERO_HISTORY_MAX_LINES", "200"))

# ---------------------------------------------------------------------------
# Slicer / source reading
# ---------------------------------------------------------------------------

SLICER_LINES_BEFORE = 3
SLICER_LINES_AFTER  = 20
DEEP_SOURCE_RADIUS  = 20

# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------

REMEDIATION_TIMEOUT = int(os.environ.get("EXITZERO_REMEDIATION_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
