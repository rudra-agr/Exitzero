from __future__ import annotations

from typing import Optional

from ..models import Diagnosis, ErrorContext, Source
from .. import config as _cfg
from .pipeline import run

# Module-level names — exposed so tests can patch them with patch.object()
PRIMARY_MODEL = _cfg.PRIMARY_MODEL
BACKUP_MODEL  = _cfg.BACKUP_MODEL


async def diagnose(ctx: ErrorContext) -> Optional[Diagnosis]:
    """
    Try the primary model first; fall back to the backup only when the primary
    returns None (timeout, parse failure, or Ollama unavailable).

    PRIMARY_MODEL and BACKUP_MODEL are read as module globals so patch.object()
    in tests works correctly.
    """
    # Access via globals() so that patch.object(fmod, "BACKUP_MODEL", ...) takes effect
    _globals = globals()
    primary = _globals["PRIMARY_MODEL"]
    backup  = _globals["BACKUP_MODEL"]

    result = await run(ctx, primary, Source.PRIMARY)
    if result is not None:
        return result

    # Always attempt backup — if it's the same model, it may still succeed
    # where the primary timed out. The warning in config.py handles the
    # "true no-op" case where both are identical and the first call succeeded.
    result = await run(ctx, backup, Source.BACKUP)
    return result
