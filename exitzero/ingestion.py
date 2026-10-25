from __future__ import annotations

import sys
from pathlib import Path


# Maximum log size accepted from --file to prevent memory exhaustion.
_MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB


def read_log(file_path: str | None = None) -> str:
    if file_path:
        path = Path(file_path)

        # Resolve symlinks and normalise the path so that traversal tricks
        # like "../../etc/passwd" are caught before we open anything.
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            print(f"exitzero: file not found — {file_path}", file=sys.stderr)
            sys.exit(2)

        if resolved.is_dir():
            print(f"exitzero: path is a directory — {file_path}", file=sys.stderr)
            sys.exit(2)

        size = resolved.stat().st_size
        if size > _MAX_LOG_BYTES:
            print(
                f"exitzero: file too large ({size} bytes, limit {_MAX_LOG_BYTES}) — {file_path}",
                file=sys.stderr,
            )
            sys.exit(2)

        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
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
