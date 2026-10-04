from __future__ import annotations

import re


_PATTERNS = [
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "0xADDR"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b"), "TIMESTAMP"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "TIME"),
    (re.compile(r"\bpid[= ]\d+\b", re.IGNORECASE), "pid=PID"),
    (re.compile(r"\b\d{5,}\b"), "NUM"),
]


def normalize(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines)
