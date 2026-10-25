# ExitZero

> **AI-powered CLI that diagnoses failing logs, explains the root cause, and proposes safe fixes — in seconds.**

ExitZero reads your test/build/runtime logs, pulls the broken source code from disk, and sends everything to a cloud LLM via OpenRouter to produce a structured diagnosis and a concrete fix. The AI does not generate a response for a human to read — it produces structured JSON that drives the system's decisions programmatically.

```bash
pytest 2>&1 | exitzero
exitzero --file error.log
```

```
Dependency Error  [High confidence]
  Line 11 of src/buggy.py
  ❯  import pandas as totally_fake_module

  What went wrong
  The code imports 'pandas' but it is not installed in the current environment.

  How to fix it
  Run: pip install pandas
```

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![OpenRouter](https://img.shields.io/badge/OpenRouter-Free%20Tier-6366F1?style=flat-square)
![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Tests](https://img.shields.io/badge/tests-162%20passing-brightgreen?style=flat-square)

---

## Table of Contents

- [How AI is Used](#how-ai-is-used)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [AI Usage Disclosure](#ai-usage-disclosure)
- [Limitations](#limitations)
- [Future Improvements](#future-improvements)

---

## How AI is Used

ExitZero uses AI as the reasoning core — not as a chatbot. Here is what the AI actually does inside the system:

**1. Source-aware reasoning**
The AI receives the raw error, the broken source code pulled from disk, and the git diff. It does not just read the error message — it reads your actual code.

**2. Agentic investigation (slow path)**
When the error has no file reference, the AI enters a tool loop. It can call `read_file`, `search_codebase`, `find_symbol`, `get_git_diff`, and `inspect_dependencies` to gather evidence before concluding. It decides which tools to call and in what order.

**3. Structured output — not chat**
The AI must respond with a strict JSON schema:

```json
{
  "done": true,
  "category": "Dependency Error | Real Bug | Environment Issue | Network Error | ...",
  "confidence": "High | Medium | Low",
  "plain_english": "what went wrong in the user's code",
  "fix_explanation": "concrete steps to fix it",
  "patch_diff": "unified diff or null",
  "shell_fix": "safe shell command or null"
}
```

This JSON is parsed, schema-validated, and used to populate a `Diagnosis` dataclass. The `Diagnosis` then drives the confidence gate, patch application, shell command execution, and UI rendering. No human reads the raw AI response.

**4. Confidence-gated action**
A deterministic gate reads the AI's confidence field and decides:
- `High` 
- `Medium` 
- `Low` 

**5. Safety layer**
Even when the AI proposes a fix, it never executes directly. Shell commands pass a deny-list (`rm -rf`, `curl | bash`, `eval`, etc.) and an allow-list (`pytest`, `pip install`, `npm test`, etc.). Patches go through `git apply --check` before `git apply`. If validation fails, the patch is reverted.

---

## Features

- **Multi-language** — Python, JavaScript, TypeScript, React, Node.js, Rust, Go, Java, Shell
- **Build tool errors** — Vite, esbuild, tsc, webpack
- **Dependency errors** — npm ENOENT, ERESOLVE, pip ImportError, missing packages
- **Network errors** — connection timeouts, SSL, ENOTFOUND, fetch failures
- **Source code aware** — pulls the exact broken lines from disk and feeds them to the LLM
- **Streaming output** — tokens appear in real time, no silent waiting
- **Safe remediation** — deny-list + allow-list + two-phase patch + automatic revert
- **JSON repair** — recovers malformed LLM output automatically (single quotes, truncated JSON, bare keys)
- **Retry with backoff** — handles transient API failures automatically
- **Cache** — SHA-256 keyed; skips the LLM on repeated identical errors
- **Python 3.12–3.14+** compatible — no nested event loops

---


### Pipeline 

```
raw log → slice errors → normalize → cache lookup → AI diagnosis → confidence gate → patch / validate / revert → output
```

### Key decisions

- **Single event loop** — `asyncio.new_event_loop()` opened once, never nested. Works on Python 3.14.
- **Fast path** — when source code is already available from disk, the tool loop is skipped entirely. Direct prompt → structured JSON.
- **Slow path** — when no file reference exists, the AI loops through up to 8 investigation steps using safe read-only tools.
- **JSON repair** — `llm/json_repair.py` (ported from [ollama-local-coding-agent](https://github.com/dontbuildwithme/ollama-local-coding-agent)) repairs malformed model output before parsing.
- **No `shell=True` anywhere** — all subprocesses use list arguments.

---

## Tech Stack

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![OpenRouter](https://img.shields.io/badge/OpenRouter-AI%20Backend-6366F1?style=for-the-badge&logo=openai&logoColor=white)
![Rich](https://img.shields.io/badge/Rich-Terminal%20UI-FAD000?style=for-the-badge&logo=windowsterminal&logoColor=black)
![pytest](https://img.shields.io/badge/pytest-162%20passing-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| LLM backend | OpenRouter API — free tier, no payment required |
| Default models | `google/gemma-4-31b-it:free`, `nvidia/nemotron-3.5-lightning:free` |
| Terminal UI | Rich (stderr) |
| HTTP | Python stdlib `urllib` — zero extra dependencies |
| Async | `asyncio` + `threading.Event` (Python 3.14 compatible) |
| Testing | pytest + pytest-asyncio (162/162 passing) |
| Config | python-dotenv |

---

## Quick Start

**Requirements:** Python 3.12+, git, free [OpenRouter](https://openrouter.ai) API key.

```bash
git clone https://github.com/your-username/exitzero.git
cd exitzero
pip install -e .
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env


## Usage

```bash
# Pipe directly
python script.py 2>&1 | python -m exitzero

# From a saved log file
python -m exitzero --file error.log

# Node/npm/Vite
npm run build 2>&1 | tee error.log && python -m exitzero --file error.log

# Pytest
pytest 2>&1 | tee error.log && python -m exitzero --file error.log
```

### Flags

| Flag | Description |
|------|-------------|
| `--file PATH` | Read log from file instead of stdin |
| `--json` | Output diagnosis as JSON array (stdout) |
| `--dry-run` | Validate fixes without executing |
| `--no-apply` | Show diagnosis only, no remediation |
| `--cache-stats` | Print cache statistics |
| `--cache-clear` | Wipe cached diagnoses |

---

## Configuration

`.env` is searched from the exitzero package directory first, then upward from the current directory. Shell variables always win.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | Required — get free at openrouter.ai |
| `EXITZERO_PRIMARY_MODEL` | `google/gemma-4-31b-it:free` | First model to try |
| `EXITZERO_BACKUP_MODEL` | `nvidia/nemotron-3.5-lightning:free` | Fallback model |
| `EXITZERO_LLM_TIMEOUT` | `60` | Seconds per model call |
| `EXITZERO_CACHE_PATH` | `~/.exitzero_cache.json` | Cache file location |
| `EXITZERO_CACHE_TTL` | `604800` | Cache lifetime in seconds (7 days) |
| `EXITZERO_CACHE_DISABLED` | `0` | Set to `1` to bypass cache |
| `EXITZERO_REMEDIATION_TIMEOUT` | `60` | Seconds for fix/validation commands |

---

## AI Usage Disclosure

AI output is consumed **programmatically** in `exitzero/llm/pipeline.py` inside the `run()` function.

The LLM receives: the error log, source code at the error location, and git diff context. It must return a structured JSON object (schema above). This JSON is:

1. Parsed by `_parse()` with malformed-JSON repair
2. Validated against `_VALID_CATEGORIES` and `_VALID_CONFIDENCES`
3. Used to populate a `Diagnosis` dataclass
4. Passed to `llm/confidence.py` to gate the action
5. Acted on by `llm/patcher.py` or `remediator.py`

The AI is not generating a displayed response. It is a reasoning engine whose structured output drives every downstream decision in the system.

---

## Limitations

- Free OpenRouter models can rate-limit on rapid consecutive calls — add `EXITZERO_CACHE_DISABLED=0` to use cache between runs
- Diagnosis accuracy depends on the model — 8b-class free models occasionally misidentify root cause on complex errors
- Source code pull only works when the error contains a valid absolute file path
- npm/Vite errors produce long `node_modules` stack traces that can distract smaller models
- Automatic patch application requires git to be initialised in the project

---

## Future Improvements

- **CI integration** — GitHub Actions plugin to run ExitZero on failed workflows automatically
- **VS Code extension** — inline diagnosis on failed test runs without leaving the editor
- **Fine-tuned model** — train on real-world error/fix pairs for higher accuracy on domain-specific errors
- **Multi-file patches** — currently limited to single-file diffs; extend to cross-file refactors
- **Auto model selection** — pick the best available free model based on error type and language
- **Web UI** — browser-based interface for teams that don't use the terminal
- **Slack / Teams bot** — post ExitZero diagnosis directly to the team channel on CI failure
- **Error pattern library** — build a local database of seen errors and known fixes for instant offline diagnosis

---

## Acknowledgements

`exitzero/llm/json_repair.py` is ported from the `jsonRepair.ts` helper in the [ollama-local-coding-agent](https://github.com/dontbuildwithme/ollama-local-coding-agent) project.

---

## License

[MIT](LICENSE)
