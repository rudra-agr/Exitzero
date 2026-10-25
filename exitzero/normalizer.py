from __future__ import annotations

import re


# Ordered from most-specific to least-specific so that longer patterns match
# before a shorter sub-pattern would consume part of the text.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ISO-8601 timestamps (with optional timezone)
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b"), "TIMESTAMP"),
    # HH:MM:SS time-only tokens
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "TIME"),
    # Hex memory addresses
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "0xADDR"),
    # PID annotations
    (re.compile(r"\bpid[= ]\d+\b", re.IGNORECASE), "pid=PID"),
    # Home-directory paths (/home/<user>/… or /Users/<user>/…) — strip
    # before the generic path rule so usernames are not leaked into cache keys.
    (re.compile(r"(?:/home|/Users)/[^/\s]+"), "/home/USER"),
    # Absolute Unix paths (keep structure, drop leading slash token)
    (re.compile(r"(?<!\w)/(?:[a-zA-Z0-9_./-]+)"), "PATH"),
    # Large standalone integers (≥5 digits) that are likely IDs / addresses
    (re.compile(r"\b\d{5,}\b"), "NUM"),
]


def normalize(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines)
