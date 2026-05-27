---
title: ADR-0012 — Long-running build hardening
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [hardening, context, delegation, background-process, ux, budget]
sources: []
---

# ADR-0012 — Long-running build hardening

## Context

Pre-S17 dogfooding on a real Hermes-driven SBL2 build session exposed a class
of failures Tern's existing design only *partially* addresses. The session
hit 59 context compactions across ~5 minutes of work — every ~2 turns the
agent rebuilt the world from a degraded summary, re-read the same files,
re-grepped for `dotenv`, forgot which port a service ran on, and verified
files it had just written.

ADR-0002 (state-replaced-each-turn) prevents *cross-turn* compaction churn —
there is no growing chat history to summarize, because every turn rebuilds
context from a canonical store. That handles the worst case the SBL screenshot
showed.

**But it does not handle**:

- A single turn that runs 60+ tool calls and overflows one model context.
- Multi-task work where six independent sub-tasks (route, schema, dep, restart,
  auth, test) all crowd the same context window.
- Background processes (a dev server) that the agent must start, leave running,
  and curl against in the same session.
- Repeated reads of the same file in the same session — wasted tokens.
- Spending $5+ on a session because no budget exists.
- Confidence — the user has no diff preview before `write_file` lands.

These are not "S17–S20 will fix it" gaps. They are an additional hardening
slice that the moat work (ADR-0011) does not cover.

## Decision

Add a hardening slice **between S20 and the closing-out work** (vision /
browser / walkthrough). It folds into the roadmap as S21, pushing vision,
browser, and walkthrough each forward by one slot.

Six concrete primitives, each landing in one src module, each with one ADR
amendment if scope creeps:

### 1) Working-set summarizer (intra-turn)

`src/tern/loop/summarize.py`

- When the assistant tool-call stack in a single turn crosses a threshold
  (default: 60% of the model's context window OR > 30 tool calls), an
  internal "summarize working set" pass runs.
- Summary replaces the older tool-result blocks with a compact recap, keeps
  the most recent 10 raw, and lets the loop continue.
- This is **not** the cross-turn compaction Hermes does. Cross-turn state
  is still replaced (ADR-0002 holds). This is intra-turn pressure relief.
- Cheap model (Haiku or Nova Lite) does the summarize call.

### 2) Sub-turn delegation

`src/tern/loop/delegate.py` + new tool `delegate(goal, context, toolset)`

- Spawns a child turn with isolated context (its own canonical message log).
- Parent only sees the child's final summary string.
- Mirrors Hermes's `delegate_task` shape but lives entirely inside Tern.
- Decomposable work (route + schema + dep + restart) becomes 4 cheap child
  turns instead of one bloated parent turn.
- Permission inheritance: child gets parent's `mode` (`safe|default|yolo`)
  unless explicitly demoted.

### 3) Background process tool

`src/tern/tools/native/proc.py` — new tool surface

- `proc(action: "start"|"poll"|"wait"|"kill"|"log", session_id?, command?)`.
- Mirrors Hermes's `process()`. Long-lived servers (dev watchers, daemons)
  start in the background, agent continues to curl/test in the same turn.
- Per-session process registry under `~/.tern/projects/<sanitized>/procs/`.
- ADR-0009's bash 3-line defense extends to `proc start` (same regex pre-screen).

### 4) Read-result cache

In `src/tern/tools/native/read_file.py`

- Content-addressed cache keyed on `(absolute_path, mtime, size)`.
- On hit: return `{"cached": true, "sha": ...}` and the model is told
  "you already have this content under turn N message M".
- Cuts repeat-read tokens to near zero on long sessions.
- Invalidated when mtime changes — correctness preserved.

### 5) Diff preview before write

In `src/tern/tools/native/write_file.py` and `src/tern/tools/native/edit_block.py`

- In `mode != "yolo"`, the tool emits a unified diff event before the write
  applies. CLI shows the diff; user accepts (Enter) / rejects (Ctrl-C).
- ADR-0003 already has the gate slot — this fills it for write tools.
- `safe` mode forces preview always; `default` previews when diff > 30 lines;
  `yolo` skips.

### 6) Session cost budgets

`tern config set budget.session 0.50` and `budget.turn 0.05`

- Loop checks accumulated cost before each new model call.
- Soft limit: warn + ask to continue.
- Hard limit: refuse the call, exit cleanly with the partial result.
- Stored in `config.json` (S16 store), enforced in `core/loop.py`.

## Alternatives considered

- **"Just buy a bigger context window"** — does not solve repeated reads or
  budget overruns. And Sonnet 200k is the ceiling we have on Bedrock.
- **Keep cross-turn compaction (Hermes-style)** — contradicts ADR-0002. Tern
  built itself around state-replaced specifically to avoid this. Reject.
- **Ship sub-turn delegation as part of S18** — too much for one session. The
  router work in S18 is already two new modules. Keep S18 focused.
- **Skip diff preview** — losing user trust on a destructive tool is worse
  than the latency. Keep.

## Consequences

- New module families: `loop/summarize.py`, `loop/delegate.py`, new tool
  `proc`, write_file diff preview hook, read_file cache.
- New dependencies: none. All stdlib + existing httpx/boto3.
- Cost goes **down** in long sessions (read cache, summarizer cuts redundant
  context) and **up** by a tiny constant (summarize call ~$0.0001/trigger).
- Spans gain `delegate_span`, `summarize_span`, `proc_span`, `cache_hit_span`.
- ADR-0002 (state-replaced-each-turn) still holds — the summarizer is
  intra-turn, the delegate child is its own state-replaced turn.
- ADR-0009 (bash 3-line defense) extends naturally to `proc start`.

## Sequencing (locked unless contradicted)

Updated full roadmap, post-ADR-0012:

- **S17** — repo-scoped memory tier (Layer A, ADR-0011 substrate). Tomorrow.
- **S18** — router + KNN recall (ADR-0011 subsystems 1+2).
- **S19** — curator with outcome priors (ADR-0011 subsystem 3).
- **S20** — StackOverflow lookup tool (justified once failure spans exist).
- **S21** — long-running build hardening (this ADR — six primitives, likely
  two sub-sessions S21a/S21b given the surface area).
- **S22** — vision (image input + screenshot tool). Was S21.
- **S23** — real search + browser_navigate/click/type. Was S22.
- **S24** — M14 polish + pipx + walkthrough. Was S23.

v1-shipped target: end of S24.
"good enough for one-shot coding" at S20.
"good enough to replace Hermes on long builds" at S21.
"differentiated against everyone else" at S23.

## Open questions for future sessions

- Working-set threshold tuning: 60% / 30 calls is a guess. Make it
  configurable; surface in `tern config`.
- Delegate child cost attribution: child cost rolls up to parent session?
  Default yes; expose `tern spans --include-children`.
- Background process cleanup: agent crash → orphaned procs. Need a
  `tern proc reap` or reaper-on-cli-start.
- Diff preview UX in non-TTY mode (CI runs): default to skipping or auto-yes
  with `TERN_NONINTERACTIVE=1`.
