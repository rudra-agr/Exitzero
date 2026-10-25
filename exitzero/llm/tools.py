from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from ..config import DEEP_SOURCE_RADIUS


_MAX_FILE_BYTES     = 50_000
_MAX_SEARCH_RESULTS = 10

# Symbol names: only valid Python/Go/Rust/JS identifiers.
_SAFE_SYMBOL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Search patterns: alphanumeric, dots, dashes, underscores, spaces — no shell
# metacharacters that could escape the grep argument.
_SAFE_PATTERN = re.compile(r"^[a-zA-Z0-9_.\-\s]{1,100}$")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Optional[Path]:
    """Return the absolute path of the nearest git repository root, or None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            shell=False,  # never use shell=True with user-derived input
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).resolve()
    except Exception:
        pass
    return None


def _safe_path(file_path: str, root: Optional[Path]) -> Optional[Path]:
    """
    Resolve *file_path* to an absolute, canonical path and verify that it:
      - exists
      - stays inside *root* (prevents directory traversal)
      - is not a directory
    Returns the resolved Path, or None if any check fails.
    """
    try:
        p = Path(file_path)
        if not p.is_absolute() and root:
            p = root / p
        # resolve() follows symlinks and eliminates ".." components.
        p = p.resolve()
        if root and not str(p).startswith(str(root)):
            return None
        if not p.exists() or p.is_dir():
            return None
        return p
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def read_file(file_path: str, line: Optional[int] = None) -> dict:
    root = _repo_root()
    path = _safe_path(file_path, root)

    if path is None:
        return {"error": f"NOT_FOUND: {file_path}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content.encode()) > _MAX_FILE_BYTES:
            if line is not None:
                lines = content.splitlines()
                start = max(0, line - DEEP_SOURCE_RADIUS - 1)
                end   = min(len(lines), line + DEEP_SOURCE_RADIUS)
                content = "\n".join(lines[start:end])
                return {"file": file_path, "lines": f"{start+1}-{end}", "content": content}
            content = content[:_MAX_FILE_BYTES] + "\n... (truncated)"
        return {"file": file_path, "content": content}
    except Exception as e:
        return {"error": str(e)}


def search_codebase(pattern: str) -> dict:
    if not _SAFE_PATTERN.match(pattern):
        return {"error": f"unsafe pattern rejected: {pattern[:60]}"}

    root = _repo_root()
    if root is None:
        return {"error": "NOT_FOUND: not inside a git repository"}

    try:
        result = subprocess.run(
            [
                "grep", "-rn",
                "--include=*.py",  "--include=*.js",  "--include=*.ts",
                "--include=*.tsx", "--include=*.jsx",
                "--include=*.go",  "--include=*.rs",  "--include=*.java",
                "--include=*.rb",  "--include=*.cs",  "--include=*.cpp",
                "--include=*.c",   "--include=*.sh",
                pattern, str(root),
            ],
            capture_output=True, text=True, timeout=10,
            shell=False,
        )
        lines = result.stdout.strip().splitlines()[:_MAX_SEARCH_RESULTS]
        if not lines:
            return {"pattern": pattern, "matches": [], "found": False}
        return {"pattern": pattern, "matches": lines, "found": True}
    except Exception as e:
        return {"error": str(e)}


def find_symbol(symbol: str) -> dict:
    if not _SAFE_SYMBOL.match(symbol):
        return {"error": f"invalid symbol name: {symbol[:60]}"}

    root = _repo_root()
    if root is None:
        return {"error": "NOT_FOUND: not inside a git repository"}

    try:
        result = subprocess.run(
            [
                "grep", "-Ern",
                "--include=*.py",  "--include=*.js",  "--include=*.ts",
                "--include=*.tsx", "--include=*.jsx",
                "--include=*.go",  "--include=*.rs",  "--include=*.java",
                "--include=*.rb",  "--include=*.cs",  "--include=*.cpp",
                f"def {symbol}|class {symbol}|func {symbol}|function {symbol}",
                str(root),
            ],
            capture_output=True, text=True, timeout=10,
            shell=False,
        )
        lines = result.stdout.strip().splitlines()[:_MAX_SEARCH_RESULTS]
        if not lines:
            return {"symbol": symbol, "definitions": [], "found": False}
        return {"symbol": symbol, "definitions": lines, "found": True}
    except Exception as e:
        return {"error": str(e)}


def get_git_diff(file_path: Optional[str] = None) -> dict:
    cmd = ["git", "diff", "HEAD"]
    if file_path:
        # Validate the path before passing it to git to prevent argument
        # injection via crafted file names that start with "-".
        root = _repo_root()
        safe = _safe_path(file_path, root)
        if safe is None:
            return {"error": f"NOT_FOUND: {file_path}"}
        cmd += ["--", str(safe)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=False)
        if result.returncode == 0:
            diff = result.stdout.strip()
            return {"diff": diff if diff else "no changes", "found": bool(diff)}
        return {"error": result.stderr.strip()}
    except Exception as e:
        return {"error": str(e)}


def get_git_status() -> dict:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
            shell=False,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            return {"status": status if status else "clean", "found": True}
        return {"error": result.stderr.strip()}
    except Exception as e:
        return {"error": str(e)}


def inspect_dependencies(language: str) -> dict:
    """
    List installed packages for *language*.

    Only "python" and "node" are supported.  The language value comes from
    the LLM and is validated against a strict allowlist before any subprocess
    is spawned — no shell injection is possible here.
    """
    try:
        if language == "python":
            result = subprocess.run(
                ["pip", "list", "--format=json"],
                capture_output=True, text=True, timeout=10,
                shell=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return {"language": language, "packages": json.loads(result.stdout), "found": True}
            return {"error": "pip list failed or returned no output"}

        if language == "node":
            result = subprocess.run(
                ["npm", "list", "--json", "--depth=0"],
                capture_output=True, text=True, timeout=10,
                shell=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return {"language": language, "packages": json.loads(result.stdout), "found": True}
            return {"error": "npm list failed or returned no output"}

        return {"error": f"NOT_FOUND: unsupported language: {language}"}
    except json.JSONDecodeError:
        return {"error": "dependency output was not valid JSON"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------

REGISTRY: dict[str, callable] = {
    "read_file":            read_file,
    "search_codebase":      search_codebase,
    "find_symbol":          find_symbol,
    "get_git_diff":         get_git_diff,
    "get_git_status":       get_git_status,
    "inspect_dependencies": inspect_dependencies,
}


def dispatch(tool_name: str, args: dict) -> dict:
    fn = REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"unknown tool: {tool_name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments for {tool_name}: {e}"}
