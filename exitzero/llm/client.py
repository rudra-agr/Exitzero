from __future__ import annotations

import asyncio
import json
import threading
import urllib.request
import urllib.error
from typing import Optional, Callable

from ..config import (
    LLM_BACKEND, LLM_TEMPERATURE, LLM_TIMEOUT,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
    PRIMARY_MODEL,
)
from .json_repair import loose_parse_object

# Import ollama at module level so tests can patch exitzero.llm.client.ollama
try:
    import ollama
except ImportError:
    ollama = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# OpenRouter backend — uses standard HTTP, no extra dependencies
# ---------------------------------------------------------------------------

def _openrouter_call(
    model: str,
    messages: list[dict],
    on_token: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    Call OpenRouter API synchronously.
    Streams if on_token provided, otherwise returns full response.
    Uses only stdlib — no httpx, no requests needed.
    """
    if not OPENROUTER_API_KEY:
        return None

    payload = {
        "model": model,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "stream": on_token is not None,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/exitzero",
            "X-Title": "ExitZero",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            if on_token is not None:
                # Streaming — read SSE chunks
                collected = []
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk_str = line[5:].strip()
                    if chunk_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(chunk_str)
                        token = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if token:
                            collected.append(token)
                            on_token(token)
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
                return "".join(collected).strip() or None
            else:
                # Non-streaming
                body = json.loads(resp.read().decode("utf-8"))
                return (
                    body.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                    or None
                )
    except urllib.error.HTTPError as e:
        # 429 rate-limit or 5xx — caller will retry
        raise
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ollama backend — kept for local use
# ---------------------------------------------------------------------------

def _ollama_call(
    model: str,
    messages: list[dict],
    on_token: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    if ollama is None:
        return None
    _ollama = ollama

    result_holder: list = []
    error_holder:  list = []
    done_event = threading.Event()

    def _run() -> None:
        try:
            if on_token:
                response = _ollama.chat(
                    model=model, messages=messages,
                    options={"temperature": LLM_TEMPERATURE}, stream=True,
                )
                if isinstance(response, dict):
                    content = response.get("message", {}).get("content", "")
                    if content:
                        on_token(content)
                    result_holder.append(content)
                    return
                collected = []
                for chunk in response:
                    token = (
                        chunk.get("message", {}).get("content", "")
                        if isinstance(chunk, dict)
                        else getattr(getattr(chunk, "message", None), "content", "") or ""
                    )
                    if token:
                        collected.append(token)
                        on_token(token)
                result_holder.append("".join(collected))
            else:
                resp = _ollama.chat(
                    model=model, messages=messages,
                    options={"temperature": LLM_TEMPERATURE},
                )
                result_holder.append(
                    resp["message"]["content"] if isinstance(resp, dict)
                    else resp.message.content
                )
        except Exception as e:
            error_holder.append(e)
        finally:
            done_event.set()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    if not done_event.wait(timeout=LLM_TIMEOUT):
        return None
    if error_holder:
        return None
    content = result_holder[0] if result_holder else None
    return content.strip() if content else None


# ---------------------------------------------------------------------------
# Unified async call — picks backend from config
# ---------------------------------------------------------------------------

async def call(
    model: str,
    messages: list[dict],
    on_token: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    Call the configured LLM backend.
    Retries up to 3 times on transient failures.
    """
    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES + 1):
        try:
            loop = asyncio.get_event_loop()

            # Fall back to ollama if openrouter key not set (e.g. in tests)
            _use_openrouter = LLM_BACKEND == "openrouter" and bool(OPENROUTER_API_KEY)
            if _use_openrouter:
                result = await loop.run_in_executor(
                    None,
                    lambda: _openrouter_call(model, messages, on_token),
                )
            else:
                # ollama backend (or openrouter fallback when no key)
                result = await loop.run_in_executor(
                    None,
                    lambda: _ollama_call(model, messages, on_token),
                )

            if result is not None:
                return result

        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
                continue
            return None
        except Exception:
            if attempt < MAX_RETRIES:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            return None

    return None
