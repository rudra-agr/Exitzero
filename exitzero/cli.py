from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from .models import Diagnosis, ErrorContext
from .llm.confidence import gate, Action
from .pipeline_runner import run_async, validate_and_apply

# Alias used by tests — they patch `exitzero.cli.pipeline_run`.
# In production this IS run_async (a coroutine function).
pipeline_run = run_async
from .remediator import execute as shell_execute
from . import cache as cache_mod
from . import ui


# ---------------------------------------------------------------------------
# Per-diagnosis remediation flow
# ---------------------------------------------------------------------------

async def _handle_one(
    ctx: ErrorContext,
    diag: Diagnosis,
    dry_run: bool,
    no_apply: bool,
) -> int:
    action = gate(diag)
    ui.header(ctx, diag)
    ui.body(diag)

    if action == Action.EXPLAIN_ONLY:
        ui.explain_only()
        return 1

    if diag.patch_diff:
        ui.diff(diag)
    elif diag.shell_fix:
        ui.shell_fix(diag)

    if no_apply:
        ui.skipped("--no-apply set")
        return 1

    if action == Action.PROMPT_USER:
        if not ui.prompt_yn():
            ui.skipped("skipped")
            return 1

    if action == Action.AUTO_APPLY:
        ui.applying()

    if diag.patch_diff:
        success, reason, failure_output = await validate_and_apply(ctx, diag)
        if success:
            ui.result_ok()
            return 0
        else:
            ui.result_fail(reason, failure_output or "")
            return 1

    elif diag.shell_fix:
        result = shell_execute(diag.shell_fix, dry_run=dry_run)
        if result.blocked_reason:
            ui.result_blocked(result.blocked_reason)
            return 1
        if result.returncode == 0:
            ui.result_ok(result.stdout)
            return 0
        else:
            ui.result_fail(detail=result.stderr)
            return 1

    return 1


# ---------------------------------------------------------------------------
# Async main — single async function, exported for test compatibility
# ---------------------------------------------------------------------------

async def _async_main(args: argparse.Namespace) -> int:
    if args.cache_stats:
        from .config import CACHE_PATH
        s = cache_mod.stats()
        ui.cache_stats(s["valid"], s["expired"], s["schema_mismatch"], str(CACHE_PATH))
        return 0

    if args.cache_clear:
        n = cache_mod.clear()
        ui.cache_cleared(n)
        return 0

    file_path: Optional[str] = args.file
    if file_path is None and sys.stdin.isatty():
        ui.bad_input()
        return 2

    # In production we call run_async (coroutine, awaited directly — no nested loop).
    # Tests patch `exitzero.cli.pipeline_run` to return a plain list, so we
    # check: if pipeline_run has been swapped out for a non-coroutine mock,
    # use it; otherwise await run_async to stay inside the current event loop.
    import inspect
    _call = pipeline_run(file_path)
    if inspect.isawaitable(_call):
        results = await _call
    else:
        results = _call

    if args.json:
        if not results:
            print("[]")
            return 0
        out = []
        for ctx, diag, conflict in results:
            if diag is None:
                out.append({"file_path": ctx.file_path, "line_number": ctx.line_number, "diagnosis": None, "conflict": conflict})
            else:
                out.append({"file_path": ctx.file_path, "line_number": ctx.line_number, "diagnosis": diag.to_dict(), "conflict": conflict, "cache_hit": diag.cache_hit})
        print(json.dumps(out, indent=2))
        return 0

    if not results:
        ui.no_errors()
        return 0

    overall_exit = 0
    for ctx, diag, conflict in results:
        if diag is None:
            ui.llm_unavailable()
            overall_exit = 1
            continue
        if conflict:
            ui.conflict_warning()
            ui.header(ctx, diag)
            ui.body(diag)
            overall_exit = 1
            continue
        code = await _handle_one(ctx, diag, args.dry_run, args.no_apply)
        if code != 0:
            overall_exit = 1

    return overall_exit


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="exitzero",
        description="Diagnose failing test/build logs with a local LLM and apply safe fixes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  pytest 2>&1 | exitzero
  exitzero --file pytest_output.log
  exitzero --file error.log --dry-run
  exitzero --file error.log --json
""",
    )
    p.add_argument("--file", "-f", metavar="PATH", help="Read log from file instead of stdin.")
    p.add_argument("--json", action="store_true", help="Emit diagnosis as JSON to stdout. No UI output.")
    p.add_argument("--dry-run", action="store_true", help="Validate proposed fixes but do not execute them.")
    p.add_argument("--no-apply", action="store_true", help="Show diagnoses and proposed fixes without applying anything.")
    p.add_argument("--cache-stats", action="store_true", help="Print cache statistics and exit.")
    p.add_argument("--cache-clear", action="store_true", help="Clear the diagnosis cache and exit.")
    return p


# ---------------------------------------------------------------------------
# Entry point — one explicit event loop, never asyncio.run()
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        exit_code = loop.run_until_complete(_async_main(args))
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    sys.exit(exit_code)
