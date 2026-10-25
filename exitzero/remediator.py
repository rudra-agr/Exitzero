from __future__ import annotations

import shlex
import subprocess
from typing import Optional

from .config import REMEDIATION_TIMEOUT
from .models import RemediationResult
from .llm.validator import _is_safe_command


def execute(
    shell_fix: str,
    dry_run: bool = False,
) -> RemediationResult:
    """
    Execute a shell_fix proposed by the LLM.

    Safety contract:
    - Command must pass _is_safe_command() (deny-list + allow-list in validator.py).
    - dry_run=True validates the command and returns without executing.
    - shell=False is always used — the command is tokenised by shlex.split()
      so no shell metacharacter interpretation occurs.
    - A timeout of REMEDIATION_TIMEOUT seconds is enforced; the result is
      marked as blocked if the process exceeds it.
    """
    safe, reason = _is_safe_command(shell_fix)
    if not safe:
        return RemediationResult(
            executed=False,
            returncode=None,
            stdout="",
            stderr="",
            blocked_reason=reason,
        )

    if dry_run:
        return RemediationResult(
            executed=False,
            returncode=0,
            stdout="",
            stderr="",
            blocked_reason=None,
        )

    try:
        result = subprocess.run(
            shlex.split(shell_fix),
            capture_output=True,
            text=True,
            timeout=REMEDIATION_TIMEOUT,
            shell=False,  # explicit: never use shell=True with LLM-generated commands
        )
        return RemediationResult(
            executed=True,
            returncode=result.returncode,
            stdout=result.stdout[-3000:],
            stderr=result.stderr[-1000:],
            blocked_reason=None,
        )
    except subprocess.TimeoutExpired:
        return RemediationResult(
            executed=True,
            returncode=None,
            stdout="",
            stderr="timed out",
            blocked_reason="execution timed out",
        )
    except Exception as e:
        return RemediationResult(
            executed=False,
            returncode=None,
            stdout="",
            stderr=str(e),
            blocked_reason=f"execution error: {e}",
        )
