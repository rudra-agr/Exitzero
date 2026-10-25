from __future__ import annotations

import json
from unittest.mock import patch, AsyncMock
import pytest

from exitzero.models import (
    Category, Confidence, Diagnosis, ErrorContext,
    Evidence, Language, Source, VerificationStatus,
)
from exitzero.llm.confidence import gate, Action
from exitzero.llm.pipeline import run as pipeline_run
from exitzero.llm.failover import diagnose
from exitzero.llm.tools import dispatch, find_symbol, search_codebase
from exitzero.llm.patcher import validate as validate_patch


def make_ctx(file_path="src/app.py", line_number=42):
    return ErrorContext(
        raw_window="AttributeError: 'NoneType' object has no attribute 'name'",
        normalized_window="AttributeError: 'NoneType' object has no attribute 'name'",
        language=Language.PYTHON,
        file_path=file_path,
        line_number=line_number,
    )


def make_diag(**kwargs):
    defaults = dict(
        category=Category.REAL_BUG,
        confidence=Confidence.HIGH,
        plain_english="A function returned None.",
        fix_explanation="Add a None check.",
        verification_status=VerificationStatus.SUPPORTED,
        evidence=[Evidence(source="read_file(src/app.py)", fact="def get_profile(): return None", observed=True)],
        patch_diff=None,
        shell_fix=None,
        source=Source.PRIMARY,
        language=Language.PYTHON,
    )
    defaults.update(kwargs)
    return Diagnosis(**defaults)


_TOOL_RESPONSE = json.dumps({
    "tool": "read_file",
    "args": {"file_path": "src/app.py", "line": 42}
})

_FINAL_RESPONSE = json.dumps({
    "done": True,
    "category": "Real Bug",
    "confidence": "High",
    "plain_english": "get_profile() returns None when no profile exists.",
    "fix_explanation": "Add a None guard before accessing .name.",
    "patch_diff": None,
    "shell_fix": None,
})


# ── Test A: known error — tool retrieves real code, evidence is real ──────────

@pytest.mark.asyncio
async def test_A_known_error_tool_retrieves_real_code():
    tool_result = {"file": "src/app.py", "content": "def get_profile(): return None"}
    with patch("exitzero.llm.pipeline.call", side_effect=[_TOOL_RESPONSE, _FINAL_RESPONSE]):
        with patch("exitzero.llm.pipeline.dispatch", return_value=tool_result):
            result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is not None
    assert result.category == Category.REAL_BUG
    assert len(result.evidence) == 1
    assert result.evidence[0].observed is True
    assert result.verification_status in (
        VerificationStatus.OBSERVED,
        VerificationStatus.SUPPORTED,
        VerificationStatus.VERIFIED,
    )


# ── Test B: missing info — agent must request a tool, not guess ───────────────

@pytest.mark.asyncio
async def test_B_insufficient_context_agent_requests_tool():
    with patch("exitzero.llm.pipeline.call", side_effect=[_TOOL_RESPONSE, _FINAL_RESPONSE]):
        with patch("exitzero.llm.pipeline.dispatch", return_value={"file": "src/app.py", "content": "..."}):
            result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is not None
    assert len(result.evidence) >= 1


# ── Test C: hallucination resistance — tool returns NOT_FOUND ─────────────────

@pytest.mark.asyncio
async def test_C_hallucination_not_found_gives_insufficient_evidence():
    not_found_result = {"error": "NOT_FOUND: src/nonexistent.py"}
    with patch("exitzero.llm.pipeline.call", side_effect=[_TOOL_RESPONSE, _FINAL_RESPONSE]):
        with patch("exitzero.llm.pipeline.dispatch", return_value=not_found_result):
            result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is not None
    assert result.verification_status == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence[0].observed is False
    assert "NOT_FOUND" in result.evidence[0].fact


# ── Test D: wrong hypothesis — contradicting evidence forces revision ──────────

@pytest.mark.asyncio
async def test_D_contradicting_evidence_produces_low_confidence():
    first_tool = json.dumps({
        "tool": "read_file",
        "args": {"file_path": "src/app.py"}
    })
    second_tool = json.dumps({
        "tool": "find_symbol",
        "args": {"symbol": "get_profile"}
    })
    revised_final = json.dumps({
        "done": True,
        "category": "Real Bug",
        "confidence": "Low",
        "plain_english": "Initial hypothesis was wrong. The function exists but returns None conditionally.",
        "fix_explanation": "Add a guard in the caller.",
        "patch_diff": None,
        "shell_fix": None,
    })
    tool_results = [
        {"file": "src/app.py", "content": "def get_profile(): return None"},
        {"symbol": "get_profile", "definitions": ["src/service.py:10: def get_profile():"], "found": True},
    ]
    with patch("exitzero.llm.pipeline.call", side_effect=[first_tool, second_tool, revised_final]):
        with patch("exitzero.llm.pipeline.dispatch", side_effect=tool_results):
            result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is not None
    assert result.confidence == Confidence.LOW
    assert len(result.evidence) == 2


# ── Test E: patch validation flow ─────────────────────────────────────────────

def test_E_patch_validation_rejects_path_traversal():
    diff = "--- a/../../../etc/passwd\n+++ b/../../../etc/passwd\n@@ -1 +1 @@\n-root\n+hacked"
    ok, reason = validate_patch(diff)
    assert not ok


def test_E_patch_validation_rejects_empty():
    ok, reason = validate_patch("")
    assert not ok


def test_E_patch_validation_rejects_blocked_path():
    diff = "--- a/.git/config\n+++ b/.git/config\n@@ -1 +1 @@\n-x\n+y"
    ok, reason = validate_patch(diff)
    assert not ok


# ── Test F: failed patch feeds new evidence back to agent ─────────────────────

@pytest.mark.asyncio
async def test_F_failed_patch_triggers_reinvestigation():
    from exitzero.pipeline_runner import validate_and_apply
    from exitzero.llm import patcher, validator

    ctx = make_ctx()
    diag = make_diag(patch_diff="--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-x\n+y")

    async def _mock_reinvestigate(ctx, failure_output):
        return None

    with patch("exitzero.pipeline_runner.apply_patch", return_value=(True, "applied")):
        with patch("exitzero.pipeline_runner.run_validation", return_value={
            "ran": True,
            "passed": False,
            "stdout": "FAILED tests/test_auth.py — TypeError: expected str",
            "stderr": "",
            "reason": "test still failing",
        }):
            with patch("exitzero.pipeline_runner.revert_patch", return_value=(True, "reverted")):
                with patch("exitzero.pipeline_runner._reinvestigate", side_effect=_mock_reinvestigate):
                    success, reason, failure_output = await validate_and_apply(ctx, diag)

    assert success is False
    assert failure_output is not None
    assert "FAILED" in failure_output or "TypeError" in failure_output


# ── Core agent loop tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_only_from_orchestrator_not_llm_claims():
    no_tool_final = json.dumps({
        "done": True,
        "category": "Real Bug",
        "confidence": "High",
        "plain_english": "Something went wrong.",
        "fix_explanation": "Fix it.",
        "patch_diff": None,
        "shell_fix": None,
    })
    with patch("exitzero.llm.pipeline.call", return_value=no_tool_final):
        result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is not None
    assert result.verification_status == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert len(result.evidence) == 0


@pytest.mark.asyncio
async def test_malformed_json_returns_none():
    with patch("exitzero.llm.pipeline.call", return_value="not json at all"):
        result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is None


@pytest.mark.asyncio
async def test_llm_unavailable_returns_none():
    with patch("exitzero.llm.pipeline.call", return_value=None):
        result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is None


@pytest.mark.asyncio
async def test_tool_call_limit_enforced_by_orchestrator():
    responses = [_TOOL_RESPONSE] * 6 + [_FINAL_RESPONSE]
    with patch("exitzero.llm.pipeline.call", side_effect=responses):
        with patch("exitzero.llm.pipeline.dispatch", return_value={"content": "x"}):
            result = await pipeline_run(make_ctx(), "qwen2.5-coder:7b", Source.PRIMARY)
    assert result is not None


@pytest.mark.asyncio
async def test_failover_to_backup():
    import exitzero.llm.failover as fmod
    backup_diag = make_diag(source=Source.BACKUP)
    mock_run = AsyncMock(side_effect=[None, backup_diag])
    with patch.object(fmod, "BACKUP_MODEL", "deepseek-coder:6.7b"):
        with patch("exitzero.llm.failover.run", mock_run):
            result = await diagnose(make_ctx())
    assert result is not None
    assert result.source == Source.BACKUP


@pytest.mark.asyncio
async def test_both_models_fail_returns_none():
    import exitzero.llm.failover as fmod
    mock_run = AsyncMock(return_value=None)
    with patch.object(fmod, "BACKUP_MODEL", "deepseek-coder:6.7b"):
        with patch("exitzero.llm.failover.run", mock_run):
            result = await diagnose(make_ctx())
    assert result is None


# ── Confidence gate tests ─────────────────────────────────────────────────────

def test_gate_supported_high_auto_apply():
    diag = make_diag(confidence=Confidence.HIGH, shell_fix="pip install fastapi",
                     verification_status=VerificationStatus.SUPPORTED)
    assert gate(diag) == Action.AUTO_APPLY


def test_gate_observed_only_explain():
    diag = make_diag(confidence=Confidence.HIGH, shell_fix="pip install fastapi",
                     verification_status=VerificationStatus.OBSERVED)
    assert gate(diag) == Action.EXPLAIN_ONLY


def test_gate_insufficient_never_auto_apply():
    diag = make_diag(confidence=Confidence.HIGH, shell_fix="pip install fastapi",
                     verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE)
    assert gate(diag) == Action.EXPLAIN_ONLY


def test_gate_medium_supported_prompt_user():
    diag = make_diag(confidence=Confidence.MEDIUM, shell_fix="pip install fastapi",
                     verification_status=VerificationStatus.SUPPORTED)
    assert gate(diag) == Action.PROMPT_USER


def test_gate_unknown_category_explain_only():
    diag = make_diag(category=Category.UNKNOWN,
                     verification_status=VerificationStatus.VERIFIED)
    assert gate(diag) == Action.EXPLAIN_ONLY


def test_gate_no_fix_explain_only():
    diag = make_diag(confidence=Confidence.HIGH, shell_fix=None, patch_diff=None,
                     verification_status=VerificationStatus.VERIFIED)
    assert gate(diag) == Action.EXPLAIN_ONLY


# ── Tool safety tests ─────────────────────────────────────────────────────────

def test_tool_dispatch_unknown_tool():
    result = dispatch("nonexistent_tool", {})
    assert "error" in result


def test_find_symbol_rejects_unsafe_input():
    result = find_symbol("../../etc/passwd")
    assert "error" in result


def test_search_codebase_rejects_unsafe_pattern():
    result = search_codebase("$(rm -rf /)")
    assert "error" in result


def test_find_symbol_not_found_is_explicit():
    result = find_symbol("totally_nonexistent_symbol_xyzabc")
    assert "error" in result or result.get("found") is False


# ── Serialisation ─────────────────────────────────────────────────────────────

def test_diagnosis_roundtrip():
    diag = make_diag()
    back = Diagnosis.from_dict(diag.to_dict())
    assert back.category == diag.category
    assert back.verification_status == diag.verification_status
    assert len(back.evidence) == len(diag.evidence)
    assert back.evidence[0].fact == diag.evidence[0].fact
    assert back.evidence[0].observed is True
