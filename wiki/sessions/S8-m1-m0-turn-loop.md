---
title: S8 — M1 + M0 turn loop and CLI
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [session, s8, m0, m1, turn-loop, cli, routing, d1]
---

# S8 — M1 + M0 turn loop and CLI (~75 min)

End of S8: `TERN_LIVE=1 tern run "say hello"` works end-to-end against
Bedrock, prints the reply, writes spans, costs ~$0.

## What was built

- `src/tern/core/turn.py` — `TurnPurpose` enum, frozen `Turn` dataclass
- `src/tern/core/routing.py` — D1 cost router skeleton (static map, lru_cache
  per model id, total over TurnPurpose)
- `src/tern/core/loop.py` — `async run_turn(turn, adapter)` async generator,
  4-event sequence, stop_reason → completion-reason mapping
- `src/tern/cli.py` — `tern run` command, TERN_LIVE gate, span recording,
  rich one-liner breadcrumbs to stderr, plain stdout for assistant text
- `tests/_fakes.py` — `FakeAdapter` test double conforming to
  `ProviderAdapter` Protocol
- `tests/test_routing.py` (4 tests) and `tests/test_loop.py` (11 tests)
- `wiki/concepts/m1-m0-turn-loop.md`

## Adapter cache surface

The Bedrock adapter now stores `last_response_message` after `complete()`.
Used by the CLI to print the assistant text after the event stream closes.
Reset per call. `FakeAdapter` mirrors this for parity.

This is a small concession to one-shot UX (the loop only emits events, not
the message); a streaming TUI in S9/M2 will read tokens off the event stream
directly and we may revisit.

## Decisions made

- D1 v0 = static map. No USD feedback / budget switching until S10 has
  session totals to feed in.
- Live calls are gated on `TERN_LIVE=1` env var. Without it, `tern run`
  exits 2 with a friendly hint. Keeps tests / `--help` / muscle-memory typos
  from burning Bedrock credits.
- Claude 4 inference-profile prefix (`us.`) goes in the routing table, not
  hidden in the adapter — the prefix is a routing concern (which deployment
  do we hit?), not an adapter concern.
- `last_response_message` lives on the adapter as a side-effect cache, not
  threaded through the loop's return type. Loop stays "yield events, return
  None"; CLI reads the cache after the stream completes.

## Failures along the way

1. First test for span tree shape expected 2 roots; recorder treats
   `turn_started` as an opener so `turn_completed` (singleton) attached as
   its child instead. Adjusted the test — recorder's behavior is correct,
   the test was wrong.
2. First live call hit `UnrecognizedClientException` because the venv
   subprocess didn't inherit AWS creds from `~/.zshrc`. Standard fix per
   memory: regex-parse the zshrc into the env dict.
3. Second live call hit `ValidationException: on-demand throughput isn't
   supported` for `anthropic.claude-sonnet-4-20250514-v1:0`. Claude 4 on
   Bedrock requires the `us.` inference profile prefix. Updated routing
   table; live call succeeded on retry.

## Gates entering S9

- pytest: 54/54 ✅ (was 39/39; +15 new)
- ruff: ✅
- mypy --strict: ✅ (18 source files; was 15)
- `tern --version` → `tern 0.0.1` ✅
- `TERN_LIVE=1 tern run "..."` → live Bedrock reply + span tree ✅

## Next: S9

M5 (slice) + M2 (slice) — two tools (`read_file`, `edit_block`), Textual TUI,
slash commands `/exit /model /status`, permission prompt for `edit_block`,
reflection loop on parse errors.

🎉 End of S9 = working coding agent, demo-visible.
