from __future__ import annotations

import subprocess

from ..models import ErrorContext


def enrich(ctx: ErrorContext) -> None:
    if ctx.file_path is None:
        return

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", ctx.file_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            ctx.git_status = result.stdout.strip()
    except Exception:
        pass
