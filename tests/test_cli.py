from __future__ import annotations

import asyncio
import json
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exitzero.cli import _build_parser, _async_main
from exitzero.models import (
    Category, Confidence, Diagnosis, ErrorContext, Evidence,
    Language, Source, VerificationStatus,
)
from exitzero.llm.confidence import Action


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ctx(file_path="src/app.py", line_number=42) -> ErrorContext:
    return ErrorContext(
        raw_window="ImportError: No module named 'requests'",
        normalized_window="ImportError: No module named 'requests'",
        language=Language.PYTHON,
        file_path=file_path,
        line_number=line_number,
    )


def _diag(
    confidence=Confidence.HIGH,
    verification_status=VerificationStatus.SUPPORTED,
    patch_diff=None,
    shell_fix="pip install requests",
    category=Category.DEPENDENCY_ERROR,
) -> Diagnosis:
    return Diagnosis(
        category=category,
        confidence=confidence,
        plain_english="The 'requests' package is missing.",
        fix_explanation="Install it with pip.",
        verification_status=verification_status,
        evidence=[Evidence(source="read_file:requirements.txt", fact="requests not listed", observed=True)],
        shell_fix=shell_fix,
        patch_diff=patch_diff,
        source=Source.PRIMARY,
        language=Language.PYTHON,
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def test_parser_defaults():
    p = _build_parser()
    args = p.parse_args([])
    assert args.file is None
    assert args.json is False
    assert args.dry_run is False
    assert args.no_apply is False
    assert args.cache_stats is False
    assert args.cache_clear is False


def test_parser_file_flag():
    p = _build_parser()
    args = p.parse_args(["--file", "error.log"])
    assert args.file == "error.log"


def test_parser_short_file_flag():
    p = _build_parser()
    args = p.parse_args(["-f", "out.txt"])
    assert args.file == "out.txt"


def test_parser_json_flag():
    p = _build_parser()
    args = p.parse_args(["--json"])
    assert args.json is True


def test_parser_dry_run_flag():
    p = _build_parser()
    args = p.parse_args(["--dry-run"])
    assert args.dry_run is True


def test_parser_no_apply_flag():
    p = _build_parser()
    args = p.parse_args(["--no-apply"])
    assert args.no_apply is True


# ---------------------------------------------------------------------------
# --cache-stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_stats_exits_zero():
    p = _build_parser()
    args = p.parse_args(["--cache-stats"])
    with patch("exitzero.cli.cache_mod") as mock_cache:
        mock_cache.stats.return_value = {"valid": 5, "expired": 1, "schema_mismatch": 0}
        code = await _async_main(args)
    assert code == 0


# ---------------------------------------------------------------------------
# --cache-clear
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_clear_exits_zero():
    p = _build_parser()
    args = p.parse_args(["--cache-clear"])
    with patch("exitzero.cli.cache_mod") as mock_cache:
        mock_cache.clear.return_value = 3
        code = await _async_main(args)
    assert code == 0


# ---------------------------------------------------------------------------
# No input
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_input_stdin_tty_exits_2(monkeypatch):
    p = _build_parser()
    args = p.parse_args([])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    code = await _async_main(args)
    assert code == 2


# ---------------------------------------------------------------------------
# Empty log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_log_exits_zero():
    p = _build_parser()
    args = p.parse_args(["--file", "some.log"])
    with patch("exitzero.cli.pipeline_run", return_value=[]):
        code = await _async_main(args)
    assert code == 0


# ---------------------------------------------------------------------------
# None diagnosis (LLM failed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_none_diagnosis_exits_1():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), None, False)]):
        code = await _async_main(args)
    assert code == 1


# ---------------------------------------------------------------------------
# --json mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_json_mode_outputs_valid_json(capsys):
    p = _build_parser()
    args = p.parse_args(["--file", "err.log", "--json"])
    diag = _diag()
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        code = await _async_main(args)
    assert code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["diagnosis"] is not None
    assert parsed[0]["conflict"] is False


@pytest.mark.asyncio
async def test_json_mode_none_diagnosis(capsys):
    p = _build_parser()
    args = p.parse_args(["--file", "err.log", "--json"])
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), None, False)]):
        code = await _async_main(args)
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["diagnosis"] is None


@pytest.mark.asyncio
async def test_json_mode_includes_cache_hit(capsys):
    p = _build_parser()
    args = p.parse_args(["--file", "err.log", "--json"])
    diag = _diag()
    diag.cache_hit = True
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        await _async_main(args)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["cache_hit"] is True


# ---------------------------------------------------------------------------
# --no-apply
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_apply_skips_remediation():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log", "--no-apply"])
    diag = _diag()
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.shell_execute") as mock_exec:
            code = await _async_main(args)
    mock_exec.assert_not_called()
    assert code == 1


# ---------------------------------------------------------------------------
# EXPLAIN_ONLY gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explain_only_no_remediation():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    diag = _diag(
        confidence=Confidence.LOW,
        verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
    )
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.shell_execute") as mock_exec:
            code = await _async_main(args)
    mock_exec.assert_not_called()
    assert code == 1


# ---------------------------------------------------------------------------
# AUTO_APPLY with shell_fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_apply_shell_fix_success():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    diag = _diag()

    mock_result = MagicMock()
    mock_result.blocked_reason = None
    mock_result.returncode = 0
    mock_result.stdout = "Successfully installed requests"
    mock_result.stderr = ""

    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.gate", return_value=Action.AUTO_APPLY):
            with patch("exitzero.cli.shell_execute", return_value=mock_result):
                code = await _async_main(args)
    assert code == 0


@pytest.mark.asyncio
async def test_auto_apply_shell_fix_failure():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    diag = _diag()

    mock_result = MagicMock()
    mock_result.blocked_reason = None
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Could not find package"

    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.gate", return_value=Action.AUTO_APPLY):
            with patch("exitzero.cli.shell_execute", return_value=mock_result):
                code = await _async_main(args)
    assert code == 1


# ---------------------------------------------------------------------------
# AUTO_APPLY with patch_diff
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_apply_patch_success():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    diag = _diag(patch_diff="--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y", shell_fix=None)

    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.gate", return_value=Action.AUTO_APPLY):
            with patch("exitzero.cli.validate_and_apply", new_callable=AsyncMock,
                       return_value=(True, "applied and validated", None)):
                code = await _async_main(args)
    assert code == 0


@pytest.mark.asyncio
async def test_auto_apply_patch_failure():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    diag = _diag(patch_diff="--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y", shell_fix=None)

    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.gate", return_value=Action.AUTO_APPLY):
            with patch("exitzero.cli.validate_and_apply", new_callable=AsyncMock,
                       return_value=(False, "tests still failing", "FAILED test_foo.py")):
                code = await _async_main(args)
    assert code == 1


# ---------------------------------------------------------------------------
# File conflict — skips auto-apply
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_skips_apply():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])
    diag = _diag()
    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, True)]):
        with patch("exitzero.cli.shell_execute") as mock_exec:
            code = await _async_main(args)
    mock_exec.assert_not_called()
    assert code == 1


# ---------------------------------------------------------------------------
# --dry-run passes through to shell_execute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_passed_to_shell_execute():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log", "--dry-run"])
    diag = _diag()

    mock_result = MagicMock()
    mock_result.blocked_reason = None
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("exitzero.cli.pipeline_run", return_value=[(_ctx(), diag, False)]):
        with patch("exitzero.cli.gate", return_value=Action.AUTO_APPLY):
            with patch("exitzero.cli.shell_execute", return_value=mock_result) as mock_exec:
                await _async_main(args)
    mock_exec.assert_called_once_with(diag.shell_fix, dry_run=True)


# ---------------------------------------------------------------------------
# Multiple errors — overall exit reflects worst outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_errors_one_fails_exit_1():
    p = _build_parser()
    args = p.parse_args(["--file", "err.log"])

    diag_ok = _diag()
    diag_low = _diag(
        confidence=Confidence.LOW,
        verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
        shell_fix=None,
    )

    mock_result_ok = MagicMock()
    mock_result_ok.blocked_reason = None
    mock_result_ok.returncode = 0
    mock_result_ok.stdout = ""
    mock_result_ok.stderr = ""

    with patch("exitzero.cli.pipeline_run", return_value=[
        (_ctx(), diag_ok, False),
        (_ctx("src/other.py", 10), diag_low, False),
    ]):
        with patch("exitzero.cli.gate", side_effect=[Action.AUTO_APPLY, Action.EXPLAIN_ONLY]):
            with patch("exitzero.cli.shell_execute", return_value=mock_result_ok):
                code = await _async_main(args)
    assert code == 1
