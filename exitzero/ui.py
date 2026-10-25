from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from .models import Diagnosis, ErrorContext, Category, Confidence, RemediationResult
from .llm.confidence import Action

console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Style maps
# ---------------------------------------------------------------------------

_CATEGORY_STYLE: dict[str, str] = {
    "Real Bug":          "bold red",
    "Flaky Test":        "yellow",
    "Git Conflict":      "bold yellow",
    "Environment Issue": "cyan",
    "Dependency Error":  "cyan",
    "Permission Error":  "magenta",
    "Network Error":     "magenta",
    "Unknown":           "dim",
}

_CONFIDENCE_STYLE: dict[str, str] = {
    "High":   "bold green",
    "Medium": "bold yellow",
    "Low":    "bold red",
}


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def header(ctx: ErrorContext, diag: Diagnosis) -> None:
    """
    Real Bug caught with confidence score of High

      Line 34 of src/app.py
      ❯  return user.get_profile().username
      ✦  return profile.username if (profile := user.get_profile()) else "anonymous"
    """
    cat_style   = _CATEGORY_STYLE.get(diag.category.value, "white")
    conf_style  = _CONFIDENCE_STYLE.get(diag.confidence.value, "white")

    title_text = Text()
    title_text.append(diag.category.value, style=cat_style)
    title_text.append(" caught with confidence score of ")
    title_text.append(diag.confidence.value, style=conf_style)

    console.print()
    console.print(title_text)

    if ctx.file_path or ctx.line_number:
        location = ""
        if ctx.line_number:
            location += f"Line {ctx.line_number}"
        if ctx.file_path:
            location += f" of {ctx.file_path}"
        console.print(f"  [dim]{location}[/dim]")

    # Source line from context snippet (if available)
    if ctx.deep_source_snippet:
        lines = ctx.deep_source_snippet.strip().splitlines()
        for line in lines[:1]:
            console.print(f"  [dim]❯  {line.strip()}[/dim]", highlight=False)

    # Proposed inline fix from patch (first + line)
    if diag.patch_diff:
        for line in diag.patch_diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                console.print(
                    f"  [green]✦  {line[1:].strip()}[/green]",
                    highlight=False,
                )
                break

    if diag.cache_hit:
        console.print("  [dim](from cache)[/dim]")


# ---------------------------------------------------------------------------
# Body — what went wrong / how to fix it
# ---------------------------------------------------------------------------

def body(diag: Diagnosis) -> None:
    console.print()
    console.print("  [bold]What went wrong[/bold]")
    console.print(f"  {diag.plain_english}")
    console.print()
    console.print("  [bold]How to fix it[/bold]")
    console.print(f"  {diag.fix_explanation}")


# ---------------------------------------------------------------------------
# Diff / shell fix display
# ---------------------------------------------------------------------------

def diff(diag: Diagnosis) -> None:
    console.print()
    console.print("  [bold]Proposed patch[/bold]")
    for line in (diag.patch_diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"  [green]{line}[/green]", highlight=False)
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"  [red]{line}[/red]", highlight=False)
        else:
            console.print(f"  [dim]{line}[/dim]", highlight=False)


def shell_fix(diag: Diagnosis) -> None:
    console.print()
    console.print("  [bold]Proposed command[/bold]")
    console.print(f"  [bold cyan]$ {diag.shell_fix}[/bold cyan]", highlight=False)


# ---------------------------------------------------------------------------
# Remediation status lines
# ---------------------------------------------------------------------------

def applying() -> None:
    console.print()
    console.print("  Applying fix automatically...", end=" ")


def result_ok(stdout: str = "") -> None:
    console.print("[bold green]✓ done[/bold green]")
    if stdout:
        console.print(f"  [dim]{stdout.strip()[:200]}[/dim]", markup=False)


def result_fail(reason: str = "", detail: str = "") -> None:
    console.print("[bold red]✗ failed[/bold red]")
    if reason:
        console.print(f"  [dim]{reason}[/dim]")
    if detail:
        console.print()
        console.print("  [dim]Validation output:[/dim]")
        for line in detail.splitlines()[:10]:
            console.print(f"  [dim]{line}[/dim]", markup=False)


def result_blocked(reason: str) -> None:
    console.print("[bold red]✗ blocked[/bold red]")
    console.print(f"  [dim]{reason}[/dim]")


def skipped(reason: str = "--no-apply set") -> None:
    console.print()
    console.print(f"  [dim]{reason} — skipping remediation.[/dim]")


def explain_only() -> None:
    console.print()
    console.print("  [dim]No fix available or confidence too low to apply.[/dim]")


def conflict_warning() -> None:
    console.print()
    console.print(
        "[bold yellow]⚠ File conflict:[/bold yellow] another fix targets "
        "the same file — skipping auto-apply for safety.",
        highlight=False,
    )


def no_errors() -> None:
    console.print("[dim]No errors detected in log.[/dim]")


def llm_unavailable() -> None:
    console.print()
    console.print("[dim]Could not diagnose this error (LLM unavailable or no result).[/dim]")


def bad_input() -> None:
    console.print(
        "[bold red]Error:[/bold red] no input. Pipe a log or use --file.",
        highlight=False,
    )


def cache_stats(valid: int, expired: int, schema_mismatch: int, path: str) -> None:
    console.print(
        f"Cache: {valid} valid, {expired} expired, {schema_mismatch} schema mismatch  [{path}]",
        highlight=False,
        markup=False,
    )


def cache_cleared(count: int) -> None:
    console.print(f"Cleared {count} cache entries.")


def prompt_yn(question: str = "  Apply this fix? [y/N] ") -> bool:
    try:
        answer = input(question).strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
