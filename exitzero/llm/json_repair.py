from __future__ import annotations

"""
Lenient JSON-object repair for tool-call arguments from small/local models.

Ported from the ollama-local-coding-agent (TypeScript) jsonRepair.ts.
Tries strict JSON first, then a bounded set of repairs, returns None if
it cannot safely recover an object. Never throws, never guesses values.
"""

import json
import re
from typing import Optional


def _try_parse(s: str) -> Optional[dict]:
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _object_candidate(s: str) -> Optional[str]:
    """Extract the tightest {...} span starting at the first '{'."""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    q = ""
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == q:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            q = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return s[start:]  # unbalanced / truncated


def _normalize_smart_quotes(s: str) -> str:
    """Replace curly/smart quotes with straight ones, outside quoted strings."""
    out = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            out.append(ch)
            in_str = True
        elif ch in "\u201c\u201d":  # " "
            out.append('"')
        elif ch in "\u2018\u2019":  # ' '
            out.append("'")
        else:
            out.append(ch)
    return "".join(out)


def _single_to_double(s: str) -> str:
    out = []
    in_single = False
    in_double = False
    esc = False
    for ch in s:
        if in_double:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_double = False
            continue
        if in_single:
            if esc:
                esc = False
                out.append(ch if ch == "'" else "\\" + ch)
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == "'":
                out.append('"')
                in_single = False
                continue
            out.append('\\"' if ch == '"' else ch)
            continue
        if ch == "'":
            out.append('"')
            in_single = True
        elif ch == '"':
            out.append('"')
            in_double = True
        else:
            out.append(ch)
    return "".join(out)


def _map_outside_strings(s: str, fn) -> str:
    out = []
    buf = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            out.append(fn("".join(buf)))
            buf = []
            out.append(ch)
            in_str = True
        else:
            buf.append(ch)
    out.append(fn("".join(buf)))
    return "".join(out)


def _quote_bare_keys(s: str) -> str:
    return _map_outside_strings(
        s, lambda seg: re.sub(r'([{,]\s*)([A-Za-z_$][\w$]*)(\s*:)', r'\1"\2"\3', seg)
    )


def _python_literals(s: str) -> str:
    def fix(seg: str) -> str:
        seg = re.sub(r'\bTrue\b', 'true', seg)
        seg = re.sub(r'\bFalse\b', 'false', seg)
        seg = re.sub(r'\bNone\b', 'null', seg)
        return seg
    return _map_outside_strings(s, fix)


def _strip_trailing_commas(s: str) -> str:
    return _map_outside_strings(s, lambda seg: re.sub(r',(\s*[}\]])', r'\1', seg))


def _close_unbalanced(s: str) -> str:
    stack = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}",  "]"):
            if stack:
                stack.pop()
    if in_str:
        return s  # truncated mid-string — don't fabricate a closing quote
    return s + "".join(reversed(stack))


_REPAIRS = [
    lambda s: s,
    _single_to_double,
    _quote_bare_keys,
    _python_literals,
    _strip_trailing_commas,
    _close_unbalanced,
    _strip_trailing_commas,  # run again after close_unbalanced
]


def loose_parse_object(s: str) -> Optional[dict]:
    """
    Best-effort parse of a JSON object from a possibly malformed string.
    Returns the object or None. Never raises.
    """
    if not isinstance(s, str) or "{" not in s:
        return None
    cand = _object_candidate(_normalize_smart_quotes(s))
    if cand is None:
        return None
    cur = cand
    for repair in _REPAIRS:
        cur = repair(cur)
        result = _try_parse(cur)
        if result is not None:
            return result
    return None
