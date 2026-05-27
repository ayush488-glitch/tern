---
title: M1 + M0 — turn loop and CLI entry
type: concept
created: 2026-05-27
updated: 2026-05-27
sources: [decisions/adr-0002-runtime-shape.md, decisions/adr-0004-provider-layer.md]
tags: [tern, m0, m1, turn-loop, cli, routing, d1]
---

# M1 + M0 — turn loop and CLI entry

S8 wired the smallest end-to-end vertical: `tern run "say hello"` does a real
Bedrock call and prints the reply. No tools yet (those land in S9). One turn,
one model, one event stream.

## What lives where

`src/tern/core/turn.py`
  `TurnPurpose` enum (ARCH, CODE, LINT, BOILERPLATE) and the frozen `Turn`
  dataclass. A Turn is a value, not a controller. Loop reads it; nobody
  mutates it.

`src/tern/core/routing.py` — D1 cost router skeleton
  `select_adapter(purpose) -> ProviderAdapter`. Static map for now (mirrors
  the token-cost-master decision tree). USD-aware fallback / budget-driven
  switch is deferred to S10. Adapters are cached per model id so `import
  tern.core.routing` does not eagerly init boto3.

  Important pitfall: Claude 4 family on Bedrock requires the `us.`
  cross-region inference profile prefix; the bare `anthropic.claude-...`
  model id raises `ValidationException: on-demand throughput isn't
  supported`. The routing table uses `us.anthropic.claude-...` accordingly.

`src/tern/core/loop.py` — M1
  `async run_turn(turn, adapter) -> AsyncIterator[TurnEvent]`. Emits
  `TurnStarted -> LLMRequested -> LLMResponded -> TurnCompleted`. The loop
  knows canonical types and the `ProviderAdapter` Protocol. Nothing else.
  No printing, no persistence — the caller decides.

`src/tern/cli.py` — M0
  Adds `tern run <prompt>`. Composes the router, builds a Turn, drains the
  event stream into a `SpanRecorder` with an `NDJSONSpanSink`. Live calls
  are gated on `TERN_LIVE=1` so an accidental `tern run` doesn't burn
  credits.

## The shape that doesn't change

The event sequence (and span tree) is the same shape S9, S10, S11 will
extend. New events get inserted between `LLMResponded` and `TurnCompleted`,
not at the ends. Tools will appear as `ToolCalled -> ToolReturned` pairs
nested under the still-open `LLMRequested`'s parent (the turn). Reflection
will appear as a new `LLMRequested -> LLMResponded` pair after a tool error.

## What stop_reason means here

The Anthropic `stop_reason` lives on `LLMResponded` (provider-level: did the
model decide to stop, run out of tokens, or call a tool?). The semantic
"why did the turn end?" lives on `TurnCompleted` (`done`, `max_steps`,
`user_abort`, `permission_denied`, `provider_error`). The loop maps the
former to the latter via `_STOP_REASON_TO_COMPLETION`. S9 will branch on
`tool_use` instead of completing.

## Tests pin

- routing: 4 purposes → 4 expected model substrings, default → sonnet,
  protocol conformance, totality over `TurnPurpose` (`tests/test_routing.py`)
- loop: event order, payload sizing on `LLMRequested`, cost passthrough on
  `LLMResponded`, stop_reason mapping, adapter receives the right messages,
  events form a clean span tree in the recorder, `Turn` is frozen
  (`tests/test_loop.py`)
- offline test double: `tests/_fakes.py` `FakeAdapter` conforms to
  `ProviderAdapter` Protocol, records calls, returns canned reply

## What S8 doesn't do

- no tools (S9)
- no multi-turn / no session (S10)
- no skills, notes, browser, MCP (S11–S13)
- routing has no USD budget feedback yet (S10)
- no streaming — the loop awaits `complete()` and yields one `LLMResponded`

## Demo

```
TERN_LIVE=1 tern run "say hello in exactly three words"
· us.anthropic.claude-sonnet-4-20250514-v1:0  in=13 out=7 $0.0000
Hello there friend.

session 4958636254f6  ·  cost $0.0000
```

```
tern spans 4958636254f6
spans · 4958636254f6  (cost $0.0000)
└── turn 0 (session 49586362)  (open)
    ├── llm us.anthropic.claude-sonnet-4-20250514-v1:0  · 13+7tok · $0.0000   1.67s
    └── turn_completed  0.0µs
```
