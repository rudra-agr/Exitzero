from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional


_MAX_DIFF_BYTES = 32_000

# Paths inside these directories should never be patched.
_BLOCKED_PATHS = re.compile(
    r"(\.git/|node_modules/|__pycache__/|\.venv/|venv/|dist/|build/)",
    re.IGNORECASE,
)


def _repo_root() -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            shell=False,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).resolve()
    except Exception:
        pass
    return None


def _extract_paths(diff: str) -> list[str]:
    """Return the list of target file paths from a unified diff."""
    paths = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[6:].strip())
    return paths


def validate(diff: str) -> tuple[bool, str]:
    if not diff or not diff.strip():
        return False, "empty diff"

    if len(diff.encode()) > _MAX_DIFF_BYTES:
        return False, f"diff exceeds {_MAX_DIFF_BYTES} byte limit"

    if not diff.strip().startswith("---"):
        return False, "does not look like a valid unified diff"

    root = _repo_root()
    paths = _extract_paths(diff)

    if not paths:
        return False, "no target files found in diff"

    for p in paths:
        # Reject path-traversal attempts regardless of OS.
        if ".." in p or p.startswith("/"):
            return False, f"path traversal detected: {p}"
        if _BLOCKED_PATHS.search(p):
            return False, f"patch targets a blocked path: {p}"
        if root:
            target = (root / p).resolve()
            # Ensure the resolved target is still under the repo root.
            if not str(target).startswith(str(root)):
                return False, f"path escapes repository: {p}"

    return True, "ok"


def apply(diff: str) -> tuple[bool, str]:
    """
    Apply *diff* to the working tree.

    Two-phase approach:
      1. ``git apply --check`` — dry-run; aborts before touching any file.
      2. ``git apply``         — actual application, only reached if (1) passed.

    This prevents a situation where a partially-applied patch leaves the tree
    in an inconsistent state.
    """
    valid, reason = validate(diff)
    if not valid:
        return False, reason

    try:
        result = subprocess.run(
            ["git", "apply", "--check", "-"],
            input=diff, capture_output=True, text=True, timeout=10,
            shell=False,
        )
        if result.returncode != 0:
            return False, f"patch does not apply cleanly: {result.stderr.strip()}"

        result = subprocess.run(
            ["git", "apply", "-"],
            input=diff, capture_output=True, text=True, timeout=10,
            shell=False,
        )
        if result.returncode != 0:
            return False, f"patch application failed: {result.stderr.strip()}"

        return True, "applied"
    except Exception as e:
        return False, str(e)


def revert(diff: str) -> tuple[bool, str]:
    """Reverse a previously applied diff."""
    try:
        result = subprocess.run(
            ["git", "apply", "--reverse", "-"],
            input=diff, capture_output=True, text=True, timeout=10,
            shell=False,
        )
        if result.returncode == 0:
            return True, "reverted"
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)
