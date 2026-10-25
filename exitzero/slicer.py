from __future__ import annotations

import re

from .models import ErrorContext, Language
from .normalizer import normalize
from .config import SLICER_LINES_BEFORE, SLICER_LINES_AFTER


# ---------------------------------------------------------------------------
# Trigger patterns — anything that signals an error worth investigating.
# Covers Python, Node/npm, Rust, Go, Java, Shell, Vite/esbuild, network,
# dependency managers, and generic timeout/permission failures.
# ---------------------------------------------------------------------------

_TRIGGERS = re.compile(
    r"("
    # Python
    r"Error|Exception|Traceback"
    # Test runners
    r"|FAILED|FAIL|ERROR"
    # Rust / Go
    r"|panic|fatal|Fatal"
    # JS/TS build tools (Vite, esbuild, Webpack, tsc)
    r"|Build failed|Transform failed|error TS\d+|SyntaxError|ReferenceError"
    r"|TypeError|RangeError|URIError|EvalError"
    # npm / yarn / pnpm
    r"|npm error|npm warn|yarn error|ERESOLVE|ENOENT|EACCES|ENOTFOUND"
    r"|ETIMEDOUT|ECONNRESET|ECONNREFUSED|EINTEGRITY"
    r"|missing peer|could not resolve|unmet peer"
    # Generic dependency / environment
    r"|ModuleNotFoundError|ImportError|ModuleError"
    r"|No module named|Cannot find module|cannot find|Could not find"
    r"|No such file|No matching distribution|version conflict"
    r"|package\.json not found|lock file|dependency"
    # Network / timeout
    r"|Connection refused|Connection reset|Connection timed out"
    r"|Timeout|timed out|TIMEOUT|request failed|fetch failed"
    r"|SSL|certificate|CERT_|getaddrinfo ENOTFOUND"
    # Permission / access
    r"|Permission denied|Access denied|EPERM|EACCES|Forbidden|403|401"
    # Segfault / low-level
    r"|segfault|SIGSEGV|core dumped|NullPointerException|OutOfMemoryError"
    # Shell / process
    r"|command not found|not recognized|is not a command|exit code [^0]"
    r"|undefined|cannot|Could not"
    r")",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Language detection — ordered from most-specific to most-generic
# ---------------------------------------------------------------------------

_LANGUAGE_SIGNALS: list[tuple[Language, re.Pattern]] = [
    (Language.PYTHON, re.compile(
        r"Traceback \(most recent call last\)|\.py\", line \d+|python.*error",
        re.IGNORECASE,
    )),
    (Language.NODE, re.compile(
        r"at .+ \(.+\.(?:js|ts|jsx|tsx):\d+:\d+\)"
        r"|UnhandledPromiseRejection"
        r"|npm error|npm warn|yarn error"
        r"|node_modules"
        r"|vite|esbuild|webpack|tsc"
        r"|\.(?:js|ts|jsx|tsx):\d+:\d+",
        re.IGNORECASE,
    )),
    (Language.RUST, re.compile(r"thread '.+' panicked at|\.rs:\d+", re.IGNORECASE)),
    (Language.GO,   re.compile(r"goroutine \d+|\.go:\d+")),
    (Language.JAVA, re.compile(r"at .+\(.+\.java:\d+\)|NullPointerException")),
    (Language.SHELL, re.compile(r"command not found|\.sh: line \d+", re.IGNORECASE)),
]


# ---------------------------------------------------------------------------
# File + line extraction — used to pull source from disk later
# ---------------------------------------------------------------------------

_FILE_LINE: list[tuple[Language, re.Pattern]] = [
    (Language.PYTHON, re.compile(r'File "(?P<path>.+\.py)", line (?P<line>\d+)')),
    # JS/TS: "at Component (src/App.tsx:15:3)" or "src/App.tsx:15:3"
    (Language.NODE,   re.compile(
        r'(?:at .+ \()?(?P<path>[^\s\(\)]+\.(?:js|ts|jsx|tsx)):(?P<line>\d+):\d+\)?'
    )),
    # Vite/esbuild: "src/pages/Home.jsx:15:2: ERROR:"
    (Language.NODE,   re.compile(
        r'(?P<path>[^\s]+\.(?:js|ts|jsx|tsx)):(?P<line>\d+):\d+[:\s]'
    )),
    (Language.RUST,   re.compile(r'(?P<path>.+\.rs):(?P<line>\d+)')),
    (Language.GO,     re.compile(r'(?P<path>.+\.go):(?P<line>\d+)')),
    (Language.JAVA,   re.compile(r'\((?P<path>.+\.java):(?P<line>\d+)\)')),
    (Language.SHELL,  re.compile(r'(?P<path>.+\.sh): line (?P<line>\d+)')),
]


# ---------------------------------------------------------------------------
# Block splitting
# ---------------------------------------------------------------------------

_TRACEBACK_START = re.compile(
    r"^(Traceback \(most recent call last\)|thread '.+' panicked|goroutine \d+)",
    re.IGNORECASE,
)

_BLOCK_SEPARATOR = re.compile(r"^[=\-]{3,}$")
_ERROR_TYPE = re.compile(r"([A-Za-z]+(?:Error|Exception|Panic|Fault))")

# npm error blocks start with "npm error" and continue until a blank line
_NPM_ERROR_START = re.compile(r"^npm (error|warn)\b", re.IGNORECASE)

# Lines that indicate passing tests — not errors, skip them as triggers
_PASSING_LINE = re.compile(r"\bPASSED\b|\bpassed\b|\bcollected \d+ items?\b")

# Blocks that are purely pytest result tables (collected / PASSED / FAILED summary lines)
# — no stack trace, just status. We keep these out of contexts.
_PYTEST_RESULTS_BLOCK = re.compile(
    r"^(collected \d+|.+::test_.+\s+(PASSED|FAILED|ERROR|SKIPPED))\s*$",
    re.IGNORECASE,
)

# One-line pytest FAILED summary: "FAILED path::test - ErrorType: msg"
# This duplicates the real traceback block — drop it.
_PYTEST_SUMMARY_LINE = re.compile(
    r"^FAILED\s+\S+\s+-\s+[A-Za-z]+(?:Error|Exception):",
    re.IGNORECASE,
)

# Build failure markers that open a new block
_BUILD_FAIL = re.compile(
    r"(Build failed|error during build|Transform failed|✘|ERROR\b)",
    re.IGNORECASE,
)


def _detect_language(log: str) -> Language:
    for language, pattern in _LANGUAGE_SIGNALS:
        if pattern.search(log):
            return language
    return Language.GENERIC


def _extract_file_line(window: str, language: Language) -> tuple[str | None, int | None]:
    # Try language-specific patterns first, then all patterns as fallback
    lang_patterns = [p for lang, p in _FILE_LINE if lang == language]
    all_patterns  = [p for _, p in _FILE_LINE]
    ordered = lang_patterns + [p for p in all_patterns if p not in lang_patterns]

    for pattern in ordered:
        match = None
        for m in pattern.finditer(window):
            match = m          # take the last match (innermost frame)
        if match:
            path = match.group("path").strip()
            # Skip node_modules paths — not user code
            if "node_modules" in path:
                continue
            return path, int(match.group("line"))
    return None, None


def _error_types_in(block: list[str]) -> set[str]:
    found = set()
    for line in block:
        for m in _ERROR_TYPE.finditer(line):
            found.add(m.group(1))
    return found


def _has_traceback(block: list[str]) -> bool:
    return any(_TRACEBACK_START.match(line.strip()) for line in block)


def _split_into_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    in_npm_block    = False
    in_traceback    = False  # True while we're inside a Python/Rust/Go traceback

    for line in lines:
        stripped = line.strip()

        if _BLOCK_SEPARATOR.match(stripped):
            if current:
                blocks.append(current)
            current = []
            in_npm_block = False
            in_traceback = False

        elif _TRACEBACK_START.match(stripped):
            if current:
                blocks.append(current)
            current = [line]
            in_npm_block = False
            in_traceback = True

        elif _NPM_ERROR_START.match(stripped):
            if not in_npm_block:
                if current:
                    blocks.append(current)
                current = [line]
                in_npm_block = True
                in_traceback = False
            else:
                current.append(line)

        elif _BUILD_FAIL.search(stripped) and not in_npm_block and not in_traceback:
            if current:
                blocks.append(current)
            current = [line]

        else:
            # End npm block on blank line
            if in_npm_block and not stripped:
                blocks.append(current)
                current = []
                in_npm_block = False
            else:
                current.append(line)
                # Once a traceback ends (blank line or a non-indented non-error line
                # after we've seen at least the "File …" line), close the traceback flag.
                if in_traceback and not stripped:
                    in_traceback = False

    if current:
        blocks.append(current)

    return [b for b in blocks if b]


def _is_pytest_noise_block(block: list[str]) -> bool:
    """Return True if the block is purely a pytest results table or summary line."""
    non_empty = [l.strip() for l in block if l.strip()]
    if not non_empty:
        return False

    # Never noise if there's a real traceback inside
    if _has_traceback(block):
        return False

    # Results table heuristic: block contains "collected N items" or
    # exclusively lines ending with PASSED / FAILED / ERROR / SKIPPED
    has_collected   = any(re.match(r"collected \d+", l, re.IGNORECASE) for l in non_empty)
    has_status_only = all(
        re.search(r"\b(PASSED|FAILED|ERROR|SKIPPED)\s*$", l, re.IGNORECASE)
        or re.match(r"collected \d+", l, re.IGNORECASE)
        for l in non_empty
    )
    if has_collected or has_status_only:
        return True

    # Single-line FAILED summary (duplicates a real traceback elsewhere)
    if len(non_empty) == 1 and _PYTEST_SUMMARY_LINE.match(non_empty[0]):
        return True

    return False


def _block_has_trigger(block: list[str]) -> bool:
    if _is_pytest_noise_block(block):
        return False
    for line in block:
        # Skip lines that only mention passing tests — not errors
        if _PASSING_LINE.search(line) and not re.search(r"(Error|Exception|FAIL\b|panic|fatal)", line, re.IGNORECASE):
            continue
        if _TRIGGERS.search(line):
            return True
    return False


# ---------------------------------------------------------------------------
# Source code extraction — pulls the offending lines from disk
# ---------------------------------------------------------------------------

def _pull_source_snippet(
    file_path: str,
    line_number: int,
    radius: int = 6,
) -> str | None:
    """
    Read `file_path` from disk and return ±`radius` lines around `line_number`.
    Returns None if the file can't be read.
    """
    try:
        from pathlib import Path
        p = Path(file_path)
        if not p.exists() or p.is_dir():
            return None
        if p.stat().st_size > 500_000:   # skip huge generated files
            return None
        source_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, line_number - radius - 1)
        end   = min(len(source_lines), line_number + radius)
        snippet_lines = []
        for i, src_line in enumerate(source_lines[start:end], start=start + 1):
            prefix = ">>>" if i == line_number else "   "
            snippet_lines.append(f"{prefix} {i:4d} | {src_line}")
        return "\n".join(snippet_lines)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def slice_log(log: str) -> list[ErrorContext]:
    lines    = log.splitlines()
    language = _detect_language(log)
    blocks   = _split_into_blocks(lines)
    trigger_blocks = [b for b in blocks if _block_has_trigger(b)]

    if not trigger_blocks:
        return []

    located:   list[tuple[str, int, list[str]]] = []
    unlocated: list[list[str]] = []

    for block in trigger_blocks:
        text = "\n".join(block)
        fp, ln = _extract_file_line(text, language)
        if fp is not None:
            located.append((fp, ln, block))
        else:
            unlocated.append(block)

    # Deduplicate by file:line
    seen_locations: set[str] = set()
    unique_located: list[list[str]] = []
    for fp, ln, block in located:
        sig = f"{fp}:{ln}"
        if sig not in seen_locations:
            seen_locations.add(sig)
            unique_located.append(block)

    # Keep unlocated blocks only if they introduce genuinely new error types
    # AND are not just one-line summaries of an already-captured traceback.
    located_error_types: set[str] = set()
    for block in unique_located:
        located_error_types |= _error_types_in(block)

    # Build a set of all raw text from located blocks for substring dedup
    located_raw_text = "\n".join("\n".join(b) for b in unique_located)

    unique_unlocated: list[list[str]] = []
    for block in unlocated:
        block_types = _error_types_in(block)
        block_text  = "\n".join(block).strip()

        # Skip if this block is a substring of an already-captured block
        # (catches pytest "FAILED …" summary lines that repeat the error type)
        if block_text and block_text in located_raw_text:
            continue

        # Skip if every error type in this block is already covered AND the
        # block has no traceback (it's just a summary line)
        if block_types and block_types.issubset(located_error_types) and not _has_traceback(block):
            continue

        if _has_traceback(block):
            unique_unlocated.append(block)
        elif block_types and not any(_error_types_in(b) == block_types for b in unique_unlocated):
            unique_unlocated.append(block)
        elif not block_types and _block_has_trigger(block):
            # Generic error lines with no recognised error type (e.g. "Error: X")
            unique_unlocated.append(block)

    # Always keep npm/network/dependency blocks — they rarely have file:line refs
    npm_blocks = [b for b in unlocated if any(_NPM_ERROR_START.match(l.strip()) for l in b)]
    for b in npm_blocks:
        if b not in unique_unlocated:
            unique_unlocated.append(b)

    final_blocks = unique_located + unique_unlocated

    all_trigger_lines: list[str] = []
    for block in final_blocks:
        for line in block:
            if _TRIGGERS.search(line.strip()):
                all_trigger_lines.append(line.strip())
                break

    contexts: list[ErrorContext] = []

    for block in final_blocks:
        raw_window = "\n".join(block)
        normalized_window = normalize(raw_window)
        file_path, line_number = _extract_file_line(raw_window, language)

        # Pull source code from disk if we have a file+line reference
        deep_source_snippet: str | None = None
        if file_path and line_number:
            deep_source_snippet = _pull_source_snippet(file_path, line_number)

        ctx = ErrorContext(
            raw_window=raw_window,
            normalized_window=normalized_window,
            language=language,
            file_path=file_path,
            line_number=line_number,
            deep_source_snippet=deep_source_snippet,
            all_errors=all_trigger_lines,
        )
        ctx._overlaps = False
        contexts.append(ctx)

    return contexts
