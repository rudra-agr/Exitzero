from __future__ import annotations

"""
Live streaming output for ExitZero.
Shows a spinner while the LLM generates — tokens are buffered silently
and only the final formatted diagnosis is shown to the user.
"""

import sys
from rich.console import Console

console = Console(stderr=True)
_buffer: list[str] = []


def start(label: str = "Analysing") -> None:
    """Print a simple spinner label — no raw tokens shown."""
    global _buffer
    _buffer = []
    console.print(f"\n[dim]{label}…[/dim]", end="", highlight=False)


def on_token(token: str) -> None:
    """Buffer tokens silently — do NOT write to stderr."""
    _buffer.append(token)


def stop() -> str:
    """End buffering, clear the spinner line, return collected text."""
    text = "".join(_buffer)
    _buffer.clear()
    # Clear the spinner line
    sys.stderr.write("\r\033[K")
    sys.stderr.flush()
    return text


def get_on_token_fn():
    return on_token
