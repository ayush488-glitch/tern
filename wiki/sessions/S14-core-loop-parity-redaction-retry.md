---
title: S14 — core-loop parity, redaction, retry
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [s14, tools, security, reliability, m12, m13]
---

# S14 — core-loop tool parity + secret redaction + Bedrock retry

## What shipped

Three things in one session:

1. **Core-loop tool parity (ADR-0009).** Four new tools — `write_file`, `glob`,
   `grep`, `bash`. Tern can now read, write, edit, find-by-name, find-by-content,
   and run shell. That's the actual coding-agent surface; until S14 we were
   missing two-thirds of it.

2. **Secret redaction (ADR-0010, M13).** New `tern.obs.redact` module wired
   into `NDJSONSpanSink`. Every span and every notes-HTML row gets scrubbed
   at the sink before write. AWS keys, GitHub/OpenAI tokens, bearer headers,
   `password=…` pairs, PEM private-key blocks, high-entropy strings. Stable
   per-session placeholders.

3. **Bedrock retry/backoff (M12).** Full-jitter exponential retry on
   throttle / 5xx / model-timeout codes, wraps both `invoke_model` and
   `invoke_model_with_response_stream`. 4 retries, base 0.5s, cap 8s.

## Code

New files
- `src/tern/tools/native/write_file.py` (3.5 KB) — destructive, refuses overwrite
  without flag, refuses directories, repo-rooted path check, 1 MB cap.
- `src/tern/tools/native/glob_tool.py` (3.4 KB) — read-only, pathlib.rglob,
  hardcoded junk-dir skip list.
- `src/tern/tools/native/grep_tool.py` (5.4 KB) — read-only, prefers `rg --json`,
  falls back to Python `re` walker with identical output shape.
- `src/tern/tools/native/bash.py` (~7 KB) — destructive + open_world, deny-list
  pre-filter (8 patterns), 200 KiB output cap with kill-on-overflow, default
  60s timeout (max 600s), `bash -lc`, cwd pinned inside repo.
- `src/tern/obs/redact.py` (~4 KB) — `Redactor` class, ordered pattern catalogue,
  stable per-session placeholders, `scrub_obj` for nested mappings.

Modified
- `src/tern/obs/sink.py` — `NDJSONSpanSink` runs `_redactor.scrub_obj()` before
  `json.dumps`. New `redact: bool = True` kwarg (default on).
- `src/tern/adapters/bedrock_anthropic.py` — `_RETRY_ERROR_CODES` frozenset,
  `_is_retryable()`, `_sleep_with_jitter()` (full jitter), retry loop wraps
  both code paths.
- `src/tern/tools/native/__init__.py` — exports for the 4 new tools.
- `src/tern/cli.py`, `src/tern/ui/app.py` — registry constructors expanded
  to 8 tools.

Tests added: 51 (write_file 8, glob 6, grep 7, bash 14, redact 9, retry 3,
plus a few helper assertions). All green.

## Gates

- pytest: 210/210 ✅ (was 159 before S14 → +51)
- ruff: ✅
- mypy --strict: ✅ (42 src files)
- `tern --version` ✅
- live Bedrock smoke: ✅ — `Hi there!` via us.anthropic.claude-sonnet-4

## Pitfalls caught

1. **Bash deny-list regex syntax.** First pass had a missing `)` in the
   `sudo rm -rf` pattern; module-import-time regex compile blew up the test
   collector. Fix: close the group. Lesson: regex tests should run as part of
   the module's own import; we already get that for free via collection.

2. **`stdout.read(N)` does not block until N bytes.** The output-cap test
   produced 250 KB but the read returned ≤200 KB on the first hop, so the
   "did we hit the cap?" branch never fired. Fix: chunked-loop reader that
   reads until EOF or `cap+1` bytes, killing the process on overflow.
   Updated test to assert on metadata flags, not on `ok=True` (kill ⇒ non-zero
   exit).

3. **`asyncio.TimeoutError` vs `TimeoutError` on Python 3.10.** They're aliased
   in 3.11+ but not in 3.10. Caught both with `except (TimeoutError,
   asyncio.TimeoutError)`. Then ruff (SIM105) wanted `contextlib.suppress` for
   the inner cleanup — added the import.

4. **AWS env vars don't survive subshell from terminal tool.** Used
   `eval "$(grep -E '^export AWS_' ~/.zshrc)"` to load them for the live smoke;
   the `for m in $(...); do export "$m"; done` shape mangled the values.
   Already documented in MEMORY for ai_native_swe; same trap here, same fix.

## Decisions parked / next session

- `web_search` tool — deferred to S15+. `web_fetch` covers the demo path; a
  real search engine integration is its own design problem.
- `gitignore`-aware glob/grep — deferred. Hardcoded junk-dir list works for now.
- Bash sandboxing (Docker / firejail / nsjail) — out of scope. Users who want
  isolation run Tern inside their own container.

## Roadmap state at end of S14

- D1 cost router: ✅ skeleton in S8, table populated through S13.
- D2 skills: ✅ S11.
- D3 session graph + replay: ✅ S10.
- D4 live HTML notes: ✅ S12 (now redaction-protected as of S14).
- D5 web_fetch (browser slot): ✅ S13.
- D6 MCP client: ✅ S13.
- M12 reliability (retry/backoff): ✅ S14.
- M13 security (secret redaction): ✅ S14.
- Core-loop tool parity: ✅ S14.

## Next session candidates

S15 options (pick one):
- `web_search` proper (Tavily/Serper/Brave — pick a provider, gate via API key)
- multi-turn agentic eval harness (run a real coding task end-to-end, score it)
- skill marketplace v0 (search + install from a registry, not just disk)
