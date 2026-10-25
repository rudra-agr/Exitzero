from __future__ import annotations

import json
import sys
from typing import Optional

from ..models import (
    Category, Confidence, Diagnosis, ErrorContext,
    Evidence, Language, Source, VerificationStatus,
)
from .client import call
from .tools import dispatch, REGISTRY
from .json_repair import loose_parse_object
from .stream_ui import start as stream_start, on_token as stream_token, stop as stream_stop
from ..config import SCHEMA_VERSION


_MAX_ITERATIONS    = 8
_MAX_TOOL_CALLS    = 6
_MAX_CONTEXT_CHARS = 24_000

_VALID_CATEGORIES  = {c.value for c in Category}
_VALID_CONFIDENCES = {c.value for c in Confidence}

# System prompt used when we already have source code — no tool calls needed
_SYSTEM_DIRECT = """\
You are an expert software debugger. Diagnose the error below and explain \
exactly how to fix it.

Rules:
- Base your diagnosis ONLY on the error log and source code provided.
- Do not reference any internal tools or functions — only the user's code.
- Be specific: name the exact file, line, and what needs to change.
- Respond ONLY with this JSON (no markdown, no preamble):
{{
  "done": true,
  "category": one of {categories},
  "confidence": "High" | "Medium" | "Low",
  "plain_english": "what went wrong, in plain language",
  "fix_explanation": "exact steps to fix it with the corrected code",
  "patch_diff": null,
  "shell_fix": null
}}"""

# System prompt used when we need to investigate via tools
_SYSTEM_TOOLS = """\
You are an expert software debugger. You investigate failures from any kind of \
log — Python, JavaScript, TypeScript, React, Node.js, npm, yarn, Vite, esbuild, \
Rust, Go, Java, Shell, network errors, dependency errors, and timeouts.

IMPORTANT: You are diagnosing errors in THE USER'S PROJECT. \
The tools below are YOUR investigation tools — NOT related to the error.

Your tools:
{tool_list}

Rules:
- Diagnose what went wrong in the user's project.
- Do NOT mention your tool names in the diagnosis output.
- Use tools to gather evidence, then give a final answer.
- Never return both a tool call and a final diagnosis together.

To call a tool:
{{"tool": "tool_name", "args": {{...}}}}

Final diagnosis:
{{
  "done": true,
  "category": one of {categories},
  "confidence": "High" | "Medium" | "Low",
  "plain_english": "what went wrong",
  "fix_explanation": "exact steps to fix it",
  "patch_diff": null,
  "shell_fix": null
}}"""

_PROMPT_DIRECT = """\
Diagnose this error and tell me exactly how to fix it.

File: {file_path}
Line: {line_number}
Toolchain: {language}

=== ERROR ===
{error_window}

=== SOURCE CODE AT ERROR LOCATION ===
{source_snippet}

Based on the source code above, what is wrong and how do I fix it?"""

_PROMPT_TOOLS = """\
Investigate this failure and determine the root cause.

Toolchain: {language}
Error file: {file_path}
Error line: {line_number}

=== ERROR LOG ===
{error_window}

=== ALL ERRORS ===
{all_errors}

Start by reading the file at the error location if one is shown."""


def _parse(raw: str) -> Optional[dict]:
    """
    Parse JSON from the model response. Uses loose_parse_object (ported from
    ollama-local-coding-agent jsonRepair.ts) to handle malformed output from
    small/weak models — single quotes, bare keys, Python literals, trailing
    commas, truncated objects, smart quotes.
    """
    if not raw:
        return None
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    # Try strict JSON first, then lenient repair
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return loose_parse_object(text)


def _is_tool_call(data: dict) -> bool:
    return "tool" in data and "args" in data and "done" not in data


def _is_final(data: dict) -> bool:
    return data.get("done") is True


def _context_size(messages: list[dict]) -> int:
    return sum(len(m["content"]) for m in messages)


def _compute_verification_status(
    evidence: list[Evidence],
    confidence: Confidence,
) -> VerificationStatus:
    if not evidence:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    observed = sum(1 for e in evidence if e.observed)
    if observed == 0:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    if confidence == Confidence.HIGH and observed >= 2:
        return VerificationStatus.SUPPORTED
    return VerificationStatus.OBSERVED


def _build_diagnosis(
    data: dict,
    source: Source,
    language: Language,
    evidence: list[Evidence],
) -> Optional[Diagnosis]:
    if data.get("category") not in _VALID_CATEGORIES:
        return None
    if data.get("confidence") not in _VALID_CONFIDENCES:
        return None

    confidence = Confidence(data["confidence"])

    return Diagnosis(
        category            = Category(data["category"]),
        confidence          = confidence,
        plain_english       = data.get("plain_english", ""),
        fix_explanation     = data.get("fix_explanation", ""),
        verification_status = _compute_verification_status(evidence, confidence),
        evidence            = evidence,
        patch_diff          = data.get("patch_diff"),
        shell_fix           = data.get("shell_fix"),
        source              = source,
        schema_version      = SCHEMA_VERSION,
        language            = language,
    )


async def run(
    ctx: ErrorContext,
    model: str,
    source: Source,
    prior_failure: Optional[str] = None,
) -> Optional[Diagnosis]:
    categories = " | ".join(_VALID_CATEGORIES)

    # --- Fast path: skip tool loop when source code already pulled from disk,
    # OR when the error is from a JS/TS/Node toolchain (Vite, esbuild, tsc)
    # where the tool loop just causes confusion.
    from ..models import Language as _Lang
    _is_node = ctx.language in (_Lang.NODE,)
    if ctx.deep_source_snippet or (_is_node and ctx.file_path):
        system  = _SYSTEM_DIRECT.format(categories=categories)
        content = _PROMPT_DIRECT.format(
            file_path      = ctx.file_path,
            line_number    = ctx.line_number or "unknown",
            language       = ctx.language.value,
            error_window   = ctx.normalized_window,
            source_snippet = ctx.deep_source_snippet,
        )
        if prior_failure:
            content += f"\n\nPrevious fix attempt failed:\n{prior_failure}\nTry a different approach."

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": content},
        ]

        for attempt in range(3):
            # Stream tokens live on first attempt so user sees output immediately
            if attempt == 0:
                stream_start("Analysing")
                raw = await call(model, messages, on_token=stream_token)
                stream_stop()
            else:
                raw = await call(model, messages)
            if raw is None:
                return None
            data = _parse(raw)
            if data and _is_final(data):
                return _build_diagnosis(data, source, ctx.language, [])
            # nudge
            messages.append({"role": "assistant", "content": raw or ""})
            messages.append({
                "role": "user",
                "content": "Reply ONLY with the JSON diagnosis object. No other text.",
            })
        return None

    # --- Slow path: use tools to gather evidence ---
    tool_list = "\n".join(f"- {name}" for name in REGISTRY)
    system    = _SYSTEM_TOOLS.format(tool_list=tool_list, categories=categories)
    all_errors_str = "\n".join(ctx.all_errors) if ctx.all_errors else "(none)"
    content   = _PROMPT_TOOLS.format(
        language     = ctx.language.value,
        file_path    = ctx.file_path   or "unknown",
        line_number  = ctx.line_number or "unknown",
        error_window = ctx.normalized_window,
        all_errors   = all_errors_str,
    )
    if prior_failure:
        content += f"\n\nPrevious fix attempt failed:\n{prior_failure}\nTry a different approach."

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": content},
    ]

    tool_call_count = 0
    iterations      = 0
    malformed_count = 0
    evidence: list[Evidence] = []

    while iterations < _MAX_ITERATIONS:
        iterations += 1

        if _context_size(messages) > _MAX_CONTEXT_CHARS:
            break

        stream_start(f"Step {iterations}")
        raw = await call(model, messages, on_token=stream_token)
        stream_stop()
        if raw is None:
            return None

        data = _parse(raw)
        if data is None:
            malformed_count += 1
            if malformed_count >= 3:
                return None
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "Reply ONLY with a tool call JSON or a final diagnosis JSON with done: true.",
            })
            continue
        malformed_count = 0

        if _is_tool_call(data):
            if tool_call_count >= _MAX_TOOL_CALLS:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"Tool limit reached. Give your final diagnosis now.",
                })
                continue

            tool_call_count += 1
            tool_name = data.get("tool", "")
            tool_args = data.get("args", {})

            messages.append({"role": "assistant", "content": raw})
            result = dispatch(tool_name, tool_args)

            if "error" not in result:
                evidence.append(Evidence(
                    source  = f"{tool_name}({json.dumps(tool_args)})",
                    fact    = json.dumps(result)[:600],
                    observed= True,
                ))
            else:
                evidence.append(Evidence(
                    source  = tool_name,
                    fact    = f"NOT_FOUND: {result['error']}",
                    observed= False,
                ))

            messages.append({
                "role": "user",
                "content": f"Tool result:\n{json.dumps(result, indent=2)}",
            })
            continue

        if _is_final(data):
            return _build_diagnosis(data, source, ctx.language, evidence)

        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": "Respond with a tool call JSON or a final diagnosis JSON with done: true.",
        })

    return None
