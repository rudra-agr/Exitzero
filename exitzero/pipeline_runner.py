from __future__ import annotations

import asyncio
from typing import Optional

from .ingestion import read_log, is_empty
from .slicer import slice_log
from .models import Diagnosis, ErrorContext, Source, VerificationStatus
from .llm.git_context import enrich
from .llm.failover import diagnose
from .llm.pipeline import run as llm_run
from .llm.patcher import apply as apply_patch, revert as revert_patch
from .llm.validator import run_validation
from .config import PRIMARY_MODEL, BACKUP_MODEL
from . import cache


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _dependency_check(
    pairs: list[tuple[ErrorContext, Optional[Diagnosis]]],
) -> list[tuple[ErrorContext, Optional[Diagnosis], bool]]:
    file_seen: set[str] = set()
    result = []
    for ctx, diag in pairs:
        if diag is None or ctx.file_path is None:
            result.append((ctx, diag, False))
            continue
        conflict = ctx.file_path in file_seen
        file_seen.add(ctx.file_path)
        result.append((ctx, diag, conflict))
    return result


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------

async def _diagnose_with_cache(ctx: ErrorContext) -> Optional[Diagnosis]:
    cached = cache.get(ctx.normalized_window)
    if cached is not None:
        cached.cache_hit = True
        return cached
    diag = await diagnose(ctx)
    if diag is not None:
        cache.set(ctx.normalized_window, diag)
    return diag


async def _run_all(contexts: list[ErrorContext]) -> list[Optional[Diagnosis]]:
    results = []
    for ctx in contexts:
        result = await _diagnose_with_cache(ctx)
        results.append(result)
        await asyncio.sleep(2)  # avoid rate limiting
    return results

async def validate_and_apply(
    ctx: ErrorContext,
    diag: Diagnosis,
) -> tuple[bool, str, Optional[str]]:
    if diag.patch_diff is None:
        return False, "no patch proposed", None

    applied, reason = apply_patch(diag.patch_diff)
    if not applied:
        return False, reason, None

    validation = run_validation(
        original_command=ctx.original_command,
        file_path=ctx.file_path,
        language=ctx.language.value,
    )

    if not validation.get("passed", False):
        revert_patch(diag.patch_diff)
        failure_output = (
            validation.get("stdout", "") + "\n" + validation.get("stderr", "")
        ).strip()
        revised = await _reinvestigate(ctx, failure_output)
        if revised is not None:
            diag.__dict__.update(revised.__dict__)
        return False, validation.get("reason", "validation failed — patch reverted"), failure_output

    diag.verification_status = VerificationStatus.VERIFIED
    return True, "applied and validated", None


async def _reinvestigate(ctx: ErrorContext, failure_output: str) -> Optional[Diagnosis]:
    result = await llm_run(ctx, PRIMARY_MODEL, Source.PRIMARY, prior_failure=failure_output)
    if result is not None:
        return result
    if BACKUP_MODEL != PRIMARY_MODEL:
        result = await llm_run(ctx, BACKUP_MODEL, Source.BACKUP, prior_failure=failure_output)
    return result


# ---------------------------------------------------------------------------
# Async pipeline — all logic lives here
# ---------------------------------------------------------------------------

async def run_async(file_path: str | None = None) -> list[tuple[ErrorContext, Optional[Diagnosis], bool]]:
    """Full async pipeline. Call this from inside an existing event loop."""
    log = read_log(file_path)
    if is_empty(log):
        return []
    contexts = slice_log(log)
    if not contexts:
        return []
    for ctx in contexts:
        enrich(ctx)
    diagnoses = await _run_all(contexts)
    pairs = list(zip(contexts, diagnoses))
    return _dependency_check(pairs)


# ---------------------------------------------------------------------------
# Sync wrapper — opens exactly one fresh loop, never nests
# ---------------------------------------------------------------------------

def run(file_path: str | None = None) -> list[tuple[ErrorContext, Optional[Diagnosis], bool]]:
    """
    Sync entry point. Opens a fresh event loop, runs the async pipeline,
    then closes it. Safe to call from anywhere — does not use asyncio.run()
    so it works on Python 3.12, 3.13, 3.14+.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_async(file_path))
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
