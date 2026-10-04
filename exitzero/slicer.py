from __future__ import annotations

import re

from .models import ErrorContext, Language
from .normalizer import normalize
from .config import SLICER_LINES_BEFORE, SLICER_LINES_AFTER


_TRIGGERS = re.compile(
    r"(Error|Exception|FAILED|FAIL|panic|fatal|Fatal|undefined|"
    r"cannot|Could not|No such|Permission denied|Connection refused|"
    r"SyntaxError|TypeError|ValueError|ImportError|ModuleNotFoundError|"
    r"NullPointerException|segfault|SIGSEGV)",
    re.IGNORECASE,
)

_LANGUAGE_SIGNALS: list[tuple[Language, re.Pattern]] = [
    (Language.PYTHON, re.compile(r"Traceback \(most recent call last\)|\.py\", line \d+")),
    (Language.NODE,   re.compile(r"at .+ \(.+\.js:\d+:\d+\)|UnhandledPromiseRejection")),
    (Language.RUST,   re.compile(r"thread '.+' panicked at|\.rs:\d+")),
    (Language.GO,     re.compile(r"goroutine \d+|\.go:\d+")),
    (Language.JAVA,   re.compile(r"at .+\(.+\.java:\d+\)|NullPointerException")),
    (Language.SHELL,  re.compile(r"command not found|\.sh: line \d+")),
]

_FILE_LINE: list[tuple[Language, re.Pattern]] = [
    (Language.PYTHON, re.compile(r'File "(?P<path>.+\.py)", line (?P<line>\d+)')),
    (Language.NODE,   re.compile(r'at .+ \((?P<path>.+\.(?:js|ts)):(?P<line>\d+):\d+\)')),
    (Language.RUST,   re.compile(r'(?P<path>.+\.rs):(?P<line>\d+)')),
    (Language.GO,     re.compile(r'(?P<path>.+\.go):(?P<line>\d+)')),
    (Language.JAVA,   re.compile(r'\((?P<path>.+\.java):(?P<line>\d+)\)')),
    (Language.SHELL,  re.compile(r'(?P<path>.+\.sh): line (?P<line>\d+)')),
]

_TRACEBACK_START = re.compile(
    r"^(Traceback \(most recent call last\)|thread '.+' panicked|goroutine \d+)",
    re.IGNORECASE,
)

_BLOCK_SEPARATOR = re.compile(r"^[=\-]{3,}$")
_ERROR_TYPE = re.compile(r"([A-Za-z]+(?:Error|Exception|Panic|Fault))")


def _detect_language(log: str) -> Language:
    for language, pattern in _LANGUAGE_SIGNALS:
        if pattern.search(log):
            return language
    return Language.GENERIC


def _extract_file_line(window: str, language: Language) -> tuple[str | None, int | None]:
    patterns = [p for lang, p in _FILE_LINE if lang == language]
    if not patterns:
        patterns = [p for _, p in _FILE_LINE]
    for pattern in patterns:
        match = None
        for m in pattern.finditer(window):
            match = m
        if match:
            return match.group("path"), int(match.group("line"))
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

    for line in lines:
        stripped = line.strip()
        if _BLOCK_SEPARATOR.match(stripped):
            if current:
                blocks.append(current)
            current = []
        elif _TRACEBACK_START.match(stripped):
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)

    if current:
        blocks.append(current)

    return [b for b in blocks if b]


def _block_has_trigger(block: list[str]) -> bool:
    return any(_TRIGGERS.search(line) for line in block)


def slice_log(log: str) -> list[ErrorContext]:
    lines = log.splitlines()
    language = _detect_language(log)
    blocks = _split_into_blocks(lines)
    trigger_blocks = [b for b in blocks if _block_has_trigger(b)]

    if not trigger_blocks:
        return []

    located: list[tuple[str, int, list[str]]] = []
    unlocated: list[list[str]] = []

    for block in trigger_blocks:
        text = "\n".join(block)
        fp, ln = _extract_file_line(text, language)
        if fp is not None:
            located.append((fp, ln, block))
        else:
            unlocated.append(block)

    seen_locations: set[str] = set()
    unique_located: list[list[str]] = []
    for fp, ln, block in located:
        sig = f"{fp}:{ln}"
        if sig not in seen_locations:
            seen_locations.add(sig)
            unique_located.append(block)

    located_error_types: set[str] = set()
    for block in unique_located:
        located_error_types |= _error_types_in(block)

    unique_unlocated: list[list[str]] = []
    for block in unlocated:
        block_types = _error_types_in(block)
        if not block_types.intersection(located_error_types):
            if _has_traceback(block):
                unique_unlocated.append(block)
            elif not any(_error_types_in(b) == block_types for b in unique_unlocated):
                unique_unlocated.append(block)

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

        ctx = ErrorContext(
            raw_window=raw_window,
            normalized_window=normalized_window,
            language=language,
            file_path=file_path,
            line_number=line_number,
            all_errors=all_trigger_lines,
        )
        ctx._overlaps = False
        contexts.append(ctx)

    return contexts
