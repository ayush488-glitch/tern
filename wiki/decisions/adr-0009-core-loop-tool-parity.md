---
title: ADR-0009 — core-loop tool surface parity
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [tools, parity, claude-code, s14, core-loop]
---

# ADR-0009 — core-loop tool surface parity

## Context

S9 shipped 4 tools: `read_file`, `edit_block`, `notes_append`, and (in S13)
`web_fetch`. That's enough for "read code, edit code, talk about code, fetch a
URL." It is not enough for the actual coding-agent core loop the way Claude Code,
Aider, Codex, and friends define it. The minimum viable parity surface is six
verbs:

  read · write · edit · find-by-name · find-by-content · run-shell

Without `bash`, the agent can't run tests, run linters, kick off a build, or
verify its own work. Without `glob`/`grep`, the agent has to ask for paths or
`read_file` everything. Without `write_file`, creating a new file requires
abusing `edit_block` against an empty target. We've been compensating by hand-
holding the agent in prompts; it is time to give it the actual tools.

The risk is obvious: `bash` is the most dangerous tool we will ever ship. Two
prior decisions cap the blast radius:

- ADR-0003 (tool surface). One protocol, two annotations that matter here:
  `destructive=True` and `open_world=True`. The permission gate already gates
  destructive on default mode and open-world on first use.
- ADR-0005 (session state). Tools are pure I/O at the boundary; every call is
  a span; redaction is centralized.

S14's job is to fill in the missing four tools without bypassing those rails.

## Decision

### Tools added (all behind the existing Tool Protocol)

| name        | annotations                          | shape                                       |
|-------------|--------------------------------------|---------------------------------------------|
| `write_file`| `destructive=True`, `read_only=False`| `path`, `content`, `overwrite=False`. Refuses overwrite without flag, refuses directory targets, 1 MB content cap, repo-rooted path validation. |
| `glob`      | `read_only=True`                     | `pattern`, optional `path`, `limit=200`. `pathlib.rglob`-backed. Hardcoded skip list: `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`. |
| `grep`      | `read_only=True`                     | `pattern`, optional `path`, `file_glob`, `case_insensitive`, `limit=200`. Prefers `rg --json` if installed; falls back to a Python `re` walker. Identical output shape (`path:line:content`) either way. |
| `bash`      | `destructive=True`, `open_world=True`| `command`, `timeout=60s` (max 600), optional `workdir`. Runs via `bash -lc`, cwd pinned inside repo, deny-list pre-filter, 200 KiB output cap (process killed on overflow). |

### Three-line defense for `bash`

1. **Registry filter (mode-level).** In `safe` mode, `bash` is invisible — the
   model never sees it.
2. **Deny-list (pattern-level).** A small allow-list of refusals: `rm -rf /`,
   `rm -rf /` with `--no-preserve-root`, fork bombs (`:(){ :|:& };:`), curl/wget
   piped into `sh`/`bash`, `dd if=/dev/zero of=/dev/sd*`, `mkfs.*`, `chmod -R 777 /`,
   `chown -R … /`, `> /dev/sd[a-z]`, `sudo rm -r…`. Pre-subprocess regex check.
3. **Permission gate (per-call).** Default mode prompts on first call (open-world)
   and on every destructive call. `yolo` skips both. `safe` never sees the tool.

The deny-list is intentionally tiny and obvious. It is not a sandbox. It catches
the LLM-generated foot-gun, not a determined adversary — that is the gate's job
and the user's job (review the prompt before approving). If you want stronger
isolation you run Tern in a container or VM; that is outside the tool's scope.

### Output cap rationale

200 KiB is enough for a noisy `pytest` run, a `cargo build`, or a `git status` on
a real repo. Anything larger is almost certainly a runaway loop or an attempt
to exfiltrate the working tree, neither of which we want pumped through Bedrock
billing. When the cap trips, the process is killed and the result includes a
`truncated: true` marker plus an explicit `[output truncated at N bytes]` tail
in the content — the model sees that it lost data, can decide whether to retry
narrower.

### Why prefer ripgrep then fall back

- If `rg` is on PATH, `--json` gives us structured matches with no shell-quoting
  pain and the speed users already expect from their own terminals.
- If `rg` is missing, the Python `re` walker has the same output shape so the
  agent doesn't see a different tool. Slower, but every dev box has Python.
- Choosing at call-time (`shutil.which`) means tests can force the fallback to
  keep CI deterministic.

### Alternatives considered

- **Skip `bash`, ship a curated "shell verb" set (`run-tests`, `run-lint`).**
  Rejected. We tried this in spirit during S9–S13 and it failed every demo —
  the agent always wanted to do *one more thing* (`git log`, `find`, `head`).
  A safe shell with a deny-list is more honest than a fake-safe verb wall.
- **Run `bash` inside a container.** Rejected for v0. Not free on macOS, not
  free on CI, and the user can already opt into one. We don't own the runtime.
- **`gitignore`-aware `glob`.** Rejected for v0. Hardcoded skip list covers ~95%
  of noise, parsing `.gitignore` properly is its own project. Revisit if it
  bites.

## Consequences

Good:
- Core-loop parity. The agent can now read, write, edit, find, search, and
  run — without hand-holding in prompts.
- All four tools share the existing protocol/registry/gate plumbing. No new
  trust boundary; the existing one got tested harder.
- The bash deny-list and 200 KiB cap are testable in isolation (8 deny patterns
  parametrized, one cap test, one timeout test).

Bad / accepted risk:
- `bash` is genuinely dangerous in `yolo` mode. Documented in the README and
  in the gate prompt. Users who type `--yolo` should know what they signed up
  for.
- Hardcoded junk-dir list will go stale (Bun? Deno? new Python tooling?).
  Acceptable — easy patch when it happens.
- Output cap can mask test failures whose useful signal lives past 200 KiB. The
  truncation marker tells the model and the user; if it bites in practice we
  raise the cap.

## References

- ADR-0003 (tool surface, permission gate, annotations)
- ADR-0005 (session state, span shape — every tool call is a span)
- Claude Code core loop tool list (raw/claude-code-internals.md)
- `src/tern/tools/native/{write_file,glob_tool,grep_tool,bash}.py`
- `tests/test_{write_file,glob_tool,grep_tool,bash}.py`
