from __future__ import annotations

import re
import shlex
import subprocess
from typing import Optional

from ..config import REMEDIATION_TIMEOUT
from .tools import _safe_path, _repo_root


# ---------------------------------------------------------------------------
# Deny-list: patterns that are NEVER allowed regardless of prefix match.
# Checked first so a crafted command like "pytest; rm -rf /" is blocked.
# ---------------------------------------------------------------------------

_BLOCKED_COMMANDS = re.compile(
    r"\b("
    r"rm\s+-rf"
    r"|rm\s+--force"
    r"|rmdir"
    r"|mkfs"
    r"|dd\s+if"
    r"|shutdown"
    r"|reboot"
    r"|poweroff"
    r"|halt"
    r"|init\s+0"
    r"|:(){ :|:&};:"           # fork bomb
    r"|chmod\s+-R\s+777"
    r"|curl.+\|\s*(?:bash|sh)" # remote code execution via pipe
    r"|wget.+\|\s*(?:bash|sh)"
    r"|eval\s"
    r"|exec\s"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Allow-list: the command must start with one of these prefixes.
# The deny-list is still checked even for allow-listed prefixes.
# ---------------------------------------------------------------------------

_ALLOWED_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "npm test",
    "npm run test",
    "yarn test",
    "cargo test",
    "go test",
    "mvn test",
    "mvn verify",
    "gradle test",
    "python -m",
    "python3 -m",
    "pip install",
    "pip3 install",
    "pip check",
    "pip3 check",
)


def _is_safe_command(cmd: str) -> tuple[bool, str]:
    """
    Two-gate safety check:
      1. Deny-list — absolute veto on destructive patterns.
      2. Allow-list — command must start with a known-safe prefix.

    Returns (True, "ok") or (False, reason).
    """
    # Gate 1: deny-list
    if _BLOCKED_COMMANDS.search(cmd):
        return False, "command matches blocked pattern"

    # Gate 2: allow-list (strip leading whitespace before prefix check)
    stripped = cmd.strip()
    if not any(stripped.startswith(p) for p in _ALLOWED_PREFIXES):
        return False, f"command not in allowed list: {stripped[:80]}"

    return True, "ok"


def _build_validation_command(
    original_command: Optional[str],
    file_path: Optional[str],
    language: str,
) -> Optional[str]:
    # Prefer the original command if it's safe to reuse.
    if original_command:
        safe, _ = _is_safe_command(original_command)
        if safe:
            return original_command

    # Derive a sensible default from the file path.
    if file_path:
        root = _repo_root()
        safe_p = _safe_path(file_path, root)
        if safe_p is not None:
            safe_str = str(safe_p)
            if language == "python":
                return f"pytest {safe_str} -x -q"
            if language == "node":
                return f"npm test -- {safe_str}"
            if language == "go":
                return f"go test ./{safe_str}"

    # Fall back to a project-wide runner.
    if language == "python":
        return "python -m pytest -x -q"

    return None


def run_validation(
    original_command: Optional[str],
    file_path: Optional[str],
    language: str,
) -> dict:
    cmd = _build_validation_command(original_command, file_path, language)

    if cmd is None:
        return {
            "ran": False,
            "reason": "could not determine a safe validation command",
        }

    safe, reason = _is_safe_command(cmd)
    if not safe:
        return {"ran": False, "reason": reason}

    try:
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=REMEDIATION_TIMEOUT,
            shell=False,  # never pass shell=True with constructed commands
        )
        return {
            "ran": True,
            "command": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-3000:],
            "stderr": result.stderr[-1000:],
            "passed": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"ran": True, "command": cmd, "passed": False, "reason": "validation timed out"}
    except Exception as e:
        return {"ran": False, "reason": str(e)}
