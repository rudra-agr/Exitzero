# ExitZero

> **AI-powered CLI that diagnoses failing logs, explains the root cause, and proposes safe fixes.**

ExitZero reads your test, build or runtime logs, pulls the broken source code from disk, and sends everything to a cloud LLM via OpenRouter. The model returns a structured JSON diagnosis, and that JSON (not free-form chat) drives the system's decisions: whether to explain, ask, or apply a fix.

```bash
pytest 2>&1 | tee error.log
python -m exitzero --file error.log
```

```
Dependency Error caught with confidence score of High
  Line 3 of tests/test_api.py

  What went wrong
  The Python module 'httpx' is not installed in the environment where
  the test is running.

  How to fix it
  Install the httpx package by running `pip install httpx`, then
  re-run the test.
```

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![OpenRouter](https://img.shields.io/badge/OpenRouter-Free%20Tier-6366F1?style=flat-square)
![Tests](https://img.shields.io/badge/tests-162%20passing-brightgreen?style=flat-square)

---

## Table of Contents

- [How AI is Used](#how-ai-is-used)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Try the Demo Folder](#try-the-demo-folder)
- [Configuration](#configuration)
- [Testing](#testing)
- [AI Usage Disclosure](#ai-usage-disclosure)
- [Limitations](#limitations)
- [Future Improvements](#future-improvements)

---

## How AI is Used

ExitZero uses AI as the reasoning core, not as a chatbot.

**1. Source-aware reasoning**
The model receives the raw error, the broken source code pulled from disk, and the git diff for the file. It reads your actual code, not just the error message.

**2. Agentic investigation (slow path)**
When no source snippet is available, the model enters a tool loop. It can call `read_file`, `search_codebase`, `find_symbol`, `get_git_diff`, `get_git_status` and `inspect_dependencies` to gather evidence before concluding. The loop is capped at 8 iterations and 6 tool calls.

**3. Structured output**
The model must respond with a strict JSON schema:

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

This JSON is parsed (with repair for malformed output), validated, and turned into a `Diagnosis` dataclass. The `Diagnosis` drives the confidence gate, patch application, command execution and UI rendering.

**4. Confidence-gated action**
A deterministic gate in `llm/confidence.py` decides what happens next:

- `High` confidence: auto-apply, but only when the diagnosis is verified or supported and has evidence from an observed file read (or has no patch to apply).
- `Medium` confidence: ask the user before doing anything.
- `Low` confidence, unknown category, unverified diagnosis, or no fix proposed: explain only, apply nothing.

**5. Safety layer**
Even when the model proposes a fix, nothing runs directly. Shell commands must pass a deny-list (`rm -rf`, `curl | bash`, `eval`, etc.) and an allow-list (`pytest`, `pip install`, `npm test`, etc.). Patches go through `git apply --check` before `git apply`, and are reverted if validation fails.

---

## Features

- **Multi-language**: Python, JavaScript, TypeScript, React, Node.js, Rust, Go, Java, Shell
- **Build tool errors**: Vite, esbuild, tsc, webpack
- **Dependency errors**: npm ENOENT and ERESOLVE, pip ImportError, missing packages
- **Network errors**: connection timeouts, SSL, ENOTFOUND, fetch failures
- **Source code aware**: pulls the broken lines from disk and sends them to the model
- **Progress indicator**: a spinner while the model works; raw JSON never leaks to the terminal
- **Safe remediation**: deny-list, allow-list, two-phase patching and automatic revert
- **JSON repair**: recovers malformed model output (single quotes, truncated JSON, bare keys)
- **Retry with backoff**: handles transient API failures
- **Model failover**: tries a primary model, then a backup model
- **Cache**: SHA-256 keyed; repeated identical errors skip the model entirely
- **Python 3.12 to 3.14**: one event loop, never nested

---

## Architecture

```
raw log -> slice errors -> normalize -> cache lookup -> AI diagnosis
        -> confidence gate -> patch / validate / revert -> output
```

### Key decisions

- **Single event loop**: `asyncio.new_event_loop()` is opened once and never nested, so it works on Python 3.14.
- **Fast path**: when source code is already available from disk (or the language is Node), the tool loop is skipped. One direct prompt returns structured JSON.
- **Slow path**: otherwise the model investigates with read-only tools, up to 8 steps.
- **Failover**: the primary model is tried first, then the backup.
- **JSON repair**: `llm/json_repair.py` (ported from [ollama-local-coding-agent](https://github.com/dontbuildwithme/ollama-local-coding-agent)) repairs malformed output before parsing.
- **No `shell=True` anywhere**: all subprocesses use list arguments.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| LLM backend | OpenRouter API (free tier, no payment required); Ollama optional for local use |
| Terminal UI | Rich (written to stderr) |
| HTTP | Python stdlib `urllib` for OpenRouter calls |
| Async | `asyncio` and `threading.Event` |
| Testing | pytest, pytest-asyncio, pytest-mock |
| Config | python-dotenv |

The `ollama` Python package is installed as a dependency so the optional local backend works.

---

## Quick Start

**Requirements:** Python 3.12+, git, and a free [OpenRouter](https://openrouter.ai) API key.

```bash
git clone https://github.com/rudra-agr/Exitzero.git
cd Exitzero

python -m venv .venv
source .venv/bin/activate          # Windows Git Bash: source .venv/Scripts/activate

pip install -e ".[dev]"
cp .env.example .env
```

Then open `.env` and set your `OPENROUTER_API_KEY`. Never commit this file; it is gitignored.

Check that it works:

```bash
python -m exitzero --help
```

---

## Usage

```bash
# Pipe directly
python script.py 2>&1 | python -m exitzero

# From a saved log file
python -m exitzero --file error.log

# Node / npm / Vite
npm run build 2>&1 | tee error.log && python -m exitzero --file error.log

# Pytest
pytest 2>&1 | tee error.log && python -m exitzero --file error.log
```

### Flags

| Flag | Description |
|------|-------------|
| `--file PATH`, `-f PATH` | Read log from file instead of stdin |
| `--json` | Output the diagnosis as a JSON array on stdout (no UI) |
| `--dry-run` | Validate proposed fixes without executing them |
| `--no-apply` | Show the diagnosis only, no remediation |
| `--cache-stats` | Print cache statistics and exit |
| `--cache-clear` | Wipe cached diagnoses and exit |

---

## Try the Demo Folder

`exitzero_test/` contains small scripts with deliberate bugs:

```bash
python exitzero_test/src/type_bug.py 2>&1 | tee error.log
python -m exitzero --file error.log --no-apply

python exitzero_test/src/network_bug.py 2>&1 | python -m exitzero --no-apply
```

See `exitzero_test/README.md` for more.

---

## Configuration

`.env` is searched upward from the current directory first, then in the project root. Variables already set in your shell always win.

| Variable | Default | Purpose |
|----------|---------|---------|
| `EXITZERO_LLM_BACKEND` | `openrouter` | `openrouter` or `ollama` |
| `OPENROUTER_API_KEY` | none | Required for OpenRouter; free at openrouter.ai |
| `EXITZERO_PRIMARY_MODEL` | `meta-llama/llama-3.1-8b-instruct:free` | First model to try |
| `EXITZERO_BACKUP_MODEL` | `google/gemma-2-9b-it:free` | Fallback model |
| `EXITZERO_LLM_TIMEOUT` | `60` | Seconds per model call |
| `EXITZERO_CACHE_PATH` | `~/.exitzero_cache.json` | Cache file location |
| `EXITZERO_CACHE_TTL` | `604800` | Cache lifetime in seconds (7 days) |
| `EXITZERO_CACHE_MAX_ENTRIES` | `500` | Maximum cached diagnoses |
| `EXITZERO_CACHE_DISABLED` | `0` | Set to `1` to bypass the cache |
| `EXITZERO_HISTORY_PATH` | `~/.exitzero_history.jsonl` | History file location |
| `EXITZERO_REMEDIATION_TIMEOUT` | `60` | Seconds for fix and validation commands |

Free OpenRouter models change often. If a default model stops working, set `EXITZERO_PRIMARY_MODEL` and `EXITZERO_BACKUP_MODEL` to any free model listed on openrouter.ai.

**Local mode:** set `EXITZERO_LLM_BACKEND=ollama` (or leave the API key empty) and run a local model such as `qwen2.5-coder:7b`.

---

## Testing

```bash
python -m pytest -q -m "not live"
```

This runs 162 tests that need no network or API key. Three additional tests are marked `live`: they call a real model, so they need a working API key or a running Ollama. On a fresh checkout without either, run the command above.

---

## AI Usage Disclosure

### How AI was used to build this project

This project was built with AI assistance.

**Claude (Anthropic)** contributed in these ways:
- **Code review and generation:**Much of the code was generated with AI assistance, including core modules such as the log slicer, the normalizer, and the cache, CLI, and LLM pipeline.
- **Code review against the spec:** compared the codebase with the project specification and found mismatches, such as the `.env` search order, the default models, and tool-call argument names.
- **Verification:** helped plan and interpret a clean-clone check of the repository (install, test suite, CLI flags, cache, JSON output, and live diagnoses).
- **Repository cleanup:** helped remove a duplicated project folder, keep secrets out of the repo, and publish a clean history.
- **Documentation:** reviewed this README against the actual code and rewrote it.


AI output is consumed programmatically in `exitzero/llm/pipeline.py`.

The model receives the error log, the source code at the error location, and git diff context. It must return a structured JSON object (schema above). That JSON is:

1. Parsed by `_parse()` with malformed-JSON repair
2. Validated against the allowed categories and confidence levels
3. Used to populate a `Diagnosis` dataclass
4. Passed to `llm/confidence.py` to gate the action
5. Acted on by `llm/patcher.py` or `remediator.py`

The explanation text is shown to the user, but the structured fields decide what the system does.

---

## Limitations

- Free OpenRouter models can rate-limit or fail on rapid consecutive calls. A failed call currently prints "Could not diagnose this error"; re-running usually works, and cached results are reused.
- Diagnosis accuracy depends on the model. Small free models can misidentify the root cause on complex errors.
- Automatic fixes require evidence from an observed file read. Some models call the investigation tools with argument names the tools do not accept, so the evidence step can fail and the diagnosis stays explain-only.
- Source code pull only works when the error contains a valid file path that exists on disk.
- npm and Vite errors produce long `node_modules` stack traces that can distract smaller models.
- Automatic patch application requires git to be initialised in the project.

---

## Future Improvements

- **CI integration**: a GitHub Actions step that runs ExitZero on failed workflows
- **VS Code extension**: inline diagnosis on failed test runs
- **Fine-tuned model**: train on real error and fix pairs for higher accuracy
- **Multi-file patches**: currently limited to single-file diffs
- **Auto model selection**: pick the best available free model by error type and language
- **Web UI** and **Slack / Teams bot** for teams that do not use the terminal
- **Error pattern library**: a local database of seen errors and known fixes for instant offline diagnosis

---

## Acknowledgements

`exitzero/llm/json_repair.py` is ported from the `jsonRepair.ts` helper in the [ollama-local-coding-agent](https://github.com/dontbuildwithme/ollama-local-coding-agent) project.