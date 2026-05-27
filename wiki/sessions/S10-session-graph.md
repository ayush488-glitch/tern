---
title: "S10 — session graph (D3)"
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [tern, session, store, replay, branch, d3, m7, phase-1]
---

# S10 — session graph (D3)

## Goal
Land D3 as a real primitive, per ADR-0005. Object store + session refs + transcripts + four CLI verbs (`log`, `resume`, `branch`, `replay`). Persist every user/assistant turn-object to disk; rebuild the canonical message log from the chain on resume.

## What shipped

**`src/tern/obs/store.py`** (~390 LOC) — content-addressed turn-object store.
- `TurnObject` frozen dataclass: role, content, parent, model_id, routing_purpose, cost, ts.
- `stable_json` + `content_hash` — sort_keys, tight separators, sha256, hex.
- Atomic writes (tempfile + os.replace), idempotent (same content → same path).
- Refs: `update_session_head`, `read_session_head`, `list_sessions`, `write_branch`, `read_branch`, `list_branches`.
- `walk_chain(head_sha)` — root → head, cycle-detected.
- `chain_to_messages(chain)` — projects back into `tuple[CanonicalMessage, ...]` for the loop.
- `persist_message(msg, ...)` — writes object + appends transcript JSONL.

**`src/tern/cli.py`** — wired persistence into `tern run`; new commands:
- `tern log [<session-prefix>]` — chain dump, root → head, with model + cost + preview.
- `tern sessions` — list sessions newest first.
- `tern resume [<session-prefix>] <prompt>` — load chain, append, run, advance head.
- `tern branch <name> [<turn-prefix>] [--session <s>]` — fork the conversation graph.
- `tern branches [<session>]` — list branches on a session.
- `tern replay [<session>]` — pure replay; verifies every child.parent equals recomputed parent hash.

**`src/tern/ui/app.py`** — chat REPL:
- New `--resume`/`-r` flag: `tern chat -r <prefix>` rehydrates history and continues.
- Every user + assistant message persists as a turn-object; head advances atomically.

**`tests/test_store.py`** (~12 tests):
- hash determinism + field-order independence
- write/read roundtrip (incl. `ToolCallBlock` blocks)
- write idempotency
- system-role rejection
- session head advance + chain walk root→head
- chain → canonical messages projection
- list_sessions newest-first
- branch fork shares parent prefix
- replay parent-link integrity check
- transcript JSONL append (one line per turn)
- cycle detection (synthetic on-disk corruption)

## Gates
- pytest 108/108 ✅ (12 new)
- ruff ✅
- mypy --strict ✅ (28 src files)
- live Bedrock end-to-end:
    - `tern run` persisted user + assistant
    - `tern log` printed 2-turn chain
    - `tern replay` ✓ hash chain consistent
    - `tern branch experiment-1` created branch ref
    - `tern resume "what was the previous reply?"` rehydrated history, fed it back to Sonnet, got context-aware reply, advanced chain to 4 turns

## Pitfalls caught + logged

- `Cost` has `usd_in` / `usd_out` (with `usd_total` as a property), NOT `usd_total` as a field. Tests originally constructed `Cost(usd_total=...)` and failed; fixed.
- `CanonicalMessage.role` is `Literal["user", "assistant", "tool", "system"]`; `TurnObject.role` is the narrower triple (no system). `persist_message` raises on `system` rather than silently widening — system messages are prompts, not turn-objects, per ADR-0005's "everything is in content" rule (system goes through provider config, not the chain).
- `walk_chain` needs explicit cycle detection. A corrupted store could create a parent-loop; we track seen hashes and raise `RuntimeError("cycle...")` rather than spin.
- Path layout decision: object dir created lazily on first `objects_dir()` call; refs the same. No `tern init` needed.

## Demo

```bash
TERN_LIVE=1 tern run "say 'session graph live' in three words exactly"
# → session cccb7538a3fe

tern log                           # 2-turn chain
tern replay                        # ✓ hash chain consistent
tern branch experiment-1           # branches at head
TERN_LIVE=1 tern resume "what was the previous reply?"
# → loads 2 turns, sends to Bedrock, advances head
tern log                           # now 4 turns + branch listed
```

## What this unlocks

- **D3 is real**, not a JSONL approximation. Every past turn is a hash; every chain is a DAG; branching forks the conversation graph without touching the workspace.
- **Replay-as-regression-test** is one CLI call. Future: `tern replay --model X` for cross-model evals (deferred until S11+ provider plumbing matures).
- **Resume across processes** works: kill the chat, come back tomorrow, `tern chat -r <prefix>` picks up exactly where you left off.

## Deferred (post-v1, per ADR-0005 §Open questions)

- `tern gc` for orphaned objects.
- `tern rebuild-index` (no `index.sqlite` yet — `list_sessions` walks the refs dir; fast enough for v1).
- `tern checkout <branch>` — branch refs exist but `chat` doesn't yet read branch-as-head; user-side workaround is `tern chat -r <session>` then re-fork via `tern branch`.
- Cross-model replay (`--model X`) — primitive in place; flag wiring is S11 work.
- Workspace branching — explicitly out of scope per ADR (git's job).

## Next session

S11 — M3 cost router (D1) end-to-end + M2 multi-provider polish. Routing decisions get logged on each turn-object's `routing_purpose` field; that field is now persisted, ready for D1 telemetry.
