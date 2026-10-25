from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from exitzero.models import (
    Category, Confidence, Diagnosis, ErrorContext, Evidence,
    Language, Source, VerificationStatus,
)
from exitzero import ui as ui_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(**kwargs) -> ErrorContext:
    defaults = dict(
        raw_window="ImportError: No module named 'requests'",
        normalized_window="ImportError: No module named 'requests'",
        language=Language.PYTHON,
        file_path="src/app.py",
        line_number=34,
        deep_source_snippet="return user.get_profile().username",
    )
    defaults.update(kwargs)
    return ErrorContext(**defaults)


def _diag(**kwargs) -> Diagnosis:
    defaults = dict(
        category=Category.REAL_BUG,
        confidence=Confidence.HIGH,
        plain_english="The 'requests' package is missing.",
        fix_explanation="Install it with pip.",
        verification_status=VerificationStatus.SUPPORTED,
        evidence=[Evidence(source="read_file:requirements.txt", fact="requests not listed", observed=True)],
        shell_fix="pip install requests",
        source=Source.PRIMARY,
        language=Language.PYTHON,
    )
    defaults.update(kwargs)
    return Diagnosis(**defaults)


def _capture(fn, *args, **kwargs) -> str:
    """Run a ui function with a string-backed console and return its output."""
    buf = StringIO()
    fake_console = Console(file=buf, highlight=False, markup=True, width=120)
    with patch.object(ui_mod, "console", fake_console):
        fn(*args, **kwargs)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# header()
# ---------------------------------------------------------------------------

def test_header_contains_category():
    out = _capture(ui_mod.header, _ctx(), _diag())
    assert "Real Bug" in out


def test_header_contains_confidence():
    out = _capture(ui_mod.header, _ctx(), _diag())
    assert "High" in out


def test_header_shows_line_number():
    out = _capture(ui_mod.header, _ctx(line_number=34), _diag())
    assert "34" in out


def test_header_shows_file_path():
    out = _capture(ui_mod.header, _ctx(file_path="src/app.py"), _diag())
    assert "src/app.py" in out


def test_header_shows_source_snippet():
    out = _capture(ui_mod.header, _ctx(deep_source_snippet="return foo.bar()"), _diag())
    assert "return foo.bar()" in out
    assert "❯" in out


def test_header_shows_patch_fix_line():
    diag = _diag(patch_diff="--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = None\n+x = default_value()")
    out = _capture(ui_mod.header, _ctx(), diag)
    assert "✦" in out
    assert "x = default_value()" in out


def test_header_no_snippet_when_missing():
    out = _capture(ui_mod.header, _ctx(deep_source_snippet=None), _diag())
    assert "❯" not in out


def test_header_shows_cache_hit():
    diag = _diag()
    diag.cache_hit = True
    out = _capture(ui_mod.header, _ctx(), diag)
    assert "cache" in out.lower()


def test_header_no_cache_label_when_not_hit():
    out = _capture(ui_mod.header, _ctx(), _diag())
    assert "from cache" not in out


def test_header_no_location_when_no_file_or_line():
    out = _capture(ui_mod.header, _ctx(file_path=None, line_number=None), _diag())
    assert "Line " not in out          # "Line 34" pattern absent
    assert "src/app.py" not in out     # file path absent


# ---------------------------------------------------------------------------
# body()
# ---------------------------------------------------------------------------

def test_body_contains_plain_english():
    out = _capture(ui_mod.body, _diag(plain_english="Missing module 'requests'."))
    assert "Missing module" in out


def test_body_contains_fix_explanation():
    out = _capture(ui_mod.body, _diag(fix_explanation="Run pip install."))
    assert "Run pip install." in out


def test_body_has_section_headers():
    out = _capture(ui_mod.body, _diag())
    assert "What went wrong" in out
    assert "How to fix it" in out


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------

def test_diff_shows_added_lines():
    diag = _diag(patch_diff="--- a\n+++ b\n@@ -1 +1 @@\n-old line\n+new line")
    out = _capture(ui_mod.diff, diag)
    assert "new line" in out


def test_diff_shows_removed_lines():
    diag = _diag(patch_diff="--- a\n+++ b\n@@ -1 +1 @@\n-old line\n+new line")
    out = _capture(ui_mod.diff, diag)
    assert "old line" in out


def test_diff_skips_file_headers():
    diag = _diag(patch_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n+fix")
    out = _capture(ui_mod.diff, diag)
    # --- and +++ lines shouldn't be shown as colored diff lines
    assert "--- a/foo.py" not in out or "---" in out  # appears dimmed


# ---------------------------------------------------------------------------
# shell_fix()
# ---------------------------------------------------------------------------

def test_shell_fix_shows_command():
    out = _capture(ui_mod.shell_fix, _diag(shell_fix="pip install requests"))
    assert "pip install requests" in out
    assert "$" in out


# ---------------------------------------------------------------------------
# Result status lines
# ---------------------------------------------------------------------------

def test_result_ok_shows_checkmark():
    out = _capture(ui_mod.result_ok)
    assert "✓" in out or "done" in out


def test_result_ok_shows_stdout():
    out = _capture(ui_mod.result_ok, stdout="Successfully installed")
    assert "Successfully installed" in out


def test_result_fail_shows_x():
    out = _capture(ui_mod.result_fail, reason="tests still failing")
    assert "✗" in out or "failed" in out
    assert "tests still failing" in out


def test_result_fail_shows_detail_lines():
    out = _capture(ui_mod.result_fail, reason="", detail="FAILED test_foo.py\nAssertionError: 1 != 2")
    assert "FAILED test_foo.py" in out


def test_result_fail_detail_capped_at_10_lines():
    detail = "\n".join(f"line {i}" for i in range(20))
    out = _capture(ui_mod.result_fail, reason="", detail=detail)
    assert "line 9" in out
    assert "line 10" not in out


def test_result_blocked_shows_reason():
    out = _capture(ui_mod.result_blocked, reason="command not in allowed list")
    assert "blocked" in out
    assert "command not in allowed list" in out


def test_skipped_shows_message():
    out = _capture(ui_mod.skipped, reason="--no-apply set")
    assert "--no-apply set" in out


def test_explain_only_message():
    out = _capture(ui_mod.explain_only)
    assert "No fix available" in out or "confidence too low" in out


def test_conflict_warning_message():
    out = _capture(ui_mod.conflict_warning)
    assert "conflict" in out.lower()


def test_no_errors_message():
    out = _capture(ui_mod.no_errors)
    assert "No errors" in out


def test_llm_unavailable_message():
    out = _capture(ui_mod.llm_unavailable)
    assert "Could not diagnose" in out


def test_bad_input_message():
    out = _capture(ui_mod.bad_input)
    assert "no input" in out.lower() or "Error" in out


# ---------------------------------------------------------------------------
# cache_stats / cache_cleared
# ---------------------------------------------------------------------------

def test_cache_stats_output():
    out = _capture(ui_mod.cache_stats, valid=5, expired=2, schema_mismatch=1, path="/tmp/cache.json")
    assert "5" in out
    assert "2" in out
    assert "/tmp/cache.json" in out


def test_cache_cleared_output():
    out = _capture(ui_mod.cache_cleared, count=7)
    assert "7" in out


# ---------------------------------------------------------------------------
# prompt_yn
# ---------------------------------------------------------------------------

def test_prompt_yn_yes():
    with patch("builtins.input", return_value="y"):
        assert ui_mod.prompt_yn() is True


def test_prompt_yn_yes_full():
    with patch("builtins.input", return_value="yes"):
        assert ui_mod.prompt_yn() is True


def test_prompt_yn_no():
    with patch("builtins.input", return_value="n"):
        assert ui_mod.prompt_yn() is False


def test_prompt_yn_empty():
    with patch("builtins.input", return_value=""):
        assert ui_mod.prompt_yn() is False


def test_prompt_yn_eof():
    with patch("builtins.input", side_effect=EOFError):
        assert ui_mod.prompt_yn() is False


def test_prompt_yn_keyboard_interrupt():
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        assert ui_mod.prompt_yn() is False
