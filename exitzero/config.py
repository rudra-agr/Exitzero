from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PRIMARY_MODEL = os.environ.get("EXITZERO_PRIMARY_MODEL", "qwen2.5-coder:7b")
BACKUP_MODEL = os.environ.get("EXITZERO_BACKUP_MODEL", "qwen2.5-coder:7b")
LLM_TEMPERATURE = 0.0
LLM_TIMEOUT = int(os.environ.get("EXITZERO_LLM_TIMEOUT", "60"))

CACHE_PATH = Path(os.environ.get("EXITZERO_CACHE_PATH", str(Path.home() / ".exitzero_cache.json")))
CACHE_TTL = int(os.environ.get("EXITZERO_CACHE_TTL", str(7 * 24 * 60 * 60)))
CACHE_MAX_ENTRIES = int(os.environ.get("EXITZERO_CACHE_MAX_ENTRIES", "500"))

HISTORY_PATH = Path(os.environ.get("EXITZERO_HISTORY_PATH", str(Path.home() / ".exitzero_history.jsonl")))
HISTORY_MAX_LINES = int(os.environ.get("EXITZERO_HISTORY_MAX_LINES", "200"))

SLICER_LINES_BEFORE = 3
SLICER_LINES_AFTER = 20
DEEP_SOURCE_RADIUS = 20

REMEDIATION_TIMEOUT = int(os.environ.get("EXITZERO_REMEDIATION_TIMEOUT", "60"))

SCHEMA_VERSION = 1
