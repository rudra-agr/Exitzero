from __future__ import annotations

import sys
from pathlib import Path


def read_log(file_path: str | None = None) -> str:
    if file_path:
        path = Path(file_path)
        if not path.exists():
            print(f"exitzero: file not found — {file_path}", file=sys.stderr)
            sys.exit(2)
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"exitzero: could not read file — {e}", file=sys.stderr)
            sys.exit(2)

    if sys.stdin.isatty():
        print("exitzero: no input — pipe a log or use --file", file=sys.stderr)
        sys.exit(2)

    try:
        return sys.stdin.read()
    except KeyboardInterrupt:
        sys.exit(2)


def is_empty(log: str) -> bool:
    return not log.strip()
