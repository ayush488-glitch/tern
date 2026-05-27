---
title: M4 — Canonical messages and the first provider adapter
type: concept
created: 2026-05-27
updated: 2026-05-27
sources: []
tags: [tern, m4, canonical, provider, adapter, bedrock, anthropic]
---

# M4 — Canonical messages and the first provider adapter

The lock got installed in S7. Internal message log is now provider-neutral, frozen,
hashable, byte-stable. One concrete adapter (Bedrock-Anthropic) translates at the edge.

Everything D1 (cost routing) and D3 (replay/branch) need to work later in the roadmap
sits on this surface. If the lock leaks (i.e. core code starts pattern-matching on
Anthropic shapes), per-turn provider switching dies silently and replay drifts.

## What got built

### `src/tern/core/canonical.py`
Frozen dataclasses with `slots=True`. Stdlib only.

- `TextBlock`, `ToolCallBlock`, `ToolResultBlock`, `ImageBlock` (union: `ContentBlock`)
- `CanonicalMessage(role, content, metadata)` — content is a tuple, not a list, so the
  message is hashable
- `Metadata(schema_version, ts, model_id, cost, seed, provenance)`
- `Cost`, `Capabilities`, `ToolSpec`, `ProviderResponse`
- `SCHEMA_VERSION = 1`
- `stable_json(msg)` — `json.dumps(asdict(msg), sort_keys=True, separators=(",",":"))`
- `content_hash(msg)` — sha256 over `stable_json`
- `from_json(blob)` — inverse, used for replay reconstruction

Why frozen dataclass and not pydantic: dataclass hashing is free, pydantic v2 is not
(re-validation on every construct). Pydantic stays scoped to M5 ToolSpec JSON-schema
generation where its `.model_json_schema()` is actually pulling weight.

Why tuples for content: lists aren't hashable. We need `content_hash()` cheap and
deterministic.

### `src/tern/core/provider.py`
`ProviderAdapter` is a `@runtime_checkable` Protocol, not a base class. Three pieces:

- `name`, `model_id`, `capabilities` attributes
- `async complete(messages, tools, *, max_tokens, temperature, cache_breakpoints)`
- pure static methods `to_wire(...)` and `from_wire(...)` for replay tests

ADR-0004 §rejected-A explicitly forbade `BaseProviderAdapter`: shared logic across
Anthropic, OpenAI, Bedrock, litellm is approximately zero (different auth, different
message shapes, different streaming, different tool wrapping). A base class either
ends up empty or becomes a god-conditional. Sibling files keep the contract honest.

### `src/tern/adapters/bedrock_anthropic.py`
First concrete adapter. Pure `to_wire` / `from_wire`, side-effecting `complete`.

The hard parts pinned by tests:

- **system role lifting.** Anthropic Messages API doesn't take a system message in
  `messages[]`. It takes a top-level `system` string. So `to_wire` walks canonical
  messages, peels off any `role == "system"`, concatenates their text with `\n\n`,
  and emits it as `body["system"]`.
- **`tool_call` → `tool_use`.** Block type, id, name, input (renamed from `args`).
- **`tool_result` rides under user-role.** Anthropic packs tool results inside a
  user-role message with `tool_result` blocks. So canonical `role == "tool"` becomes
  wire `role == "user"` carrying the result blocks. `ok=False` adds `is_error: true`.
- **`ToolSpec` wraps BARE.** `{name, description, input_schema}`. NOT the OpenAI
  `{type: "function", function: {...}}` wrapper. (This is exactly the schema
  incompatibility that breaks Kimi K2.5 on Bedrock today — see token-cost-master
  pitfall.)
- **`cache_breakpoints` apply at indices.** `to_wire(messages, cache_breakpoints=(0, 5))`
  attaches `cache_control: {type: "ephemeral"}` to the last block of message 0 and
  message 5. This is how prompt caching gets requested per-turn without burying the
  knob inside `complete()`.
- **`from_wire` parses a Messages-API response.** Reads `content[]` (text + tool_use),
  `usage` (input_tokens / output_tokens — USD pricing happens later in routing),
  `stop_reason`, `id`. Returns `ProviderResponse`.

`complete()` lazy-imports nothing; boto3 is a top-level dep now. It calls
`bedrock-runtime.invoke_model`, decodes the body, hands it to `from_wire`. Tests mock
`boto3.client` so the suite stays offline.

## What this unlocks

- **D1 (per-turn cost routing).** S8 will add `core/routing.py` reading a `TurnPurpose`
  enum from the agent loop and picking an adapter. The selector returns the same
  Protocol type, so the loop stays adapter-blind.
- **D3 (replay/branch).** `content_hash` over `stable_json` gives content-addressable
  message storage. Branching becomes "fork the tuple at index N, swap the message,
  re-run from there." No mutation, no aliasing.
- **Multi-provider reach.** OpenAI, Anthropic-direct, Mistral, Vertex all become
  sibling adapters under `src/tern/adapters/`. They share the canonical types and
  nothing else.

## Pitfalls hit + recorded

- `from typing import Union` plus `X | Y` — ruff (UP007) flags the `Union`. We use
  PEP 604 unions everywhere.
- `Pyright` initially complained about `cls(**d)` returning `ContentBlock`; mypy
  was fine. We dropped the `# type: ignore` once mypy --strict passed cleanly.
- `boto3` has no `py.typed` marker, so mypy --strict refuses to import it. Fix:
  `boto3-stubs[bedrock-runtime]>=1.34` in dev deps.

## What's NOT in M4 (deferred)

- D1 routing policy / `core/routing.py` — needs `TurnPurpose` from M3 (agent loop).
  Lands in S8.
- Live Bedrock end-to-end via `complete()` — credentials are in `~/.zshrc`, but the
  agent loop that calls `complete()` doesn't exist yet. Lands in S8 alongside M3.
- Per-token USD pricing tables — sit as adapter-side constants today. Move to
  config in S10. ADR-0004 left this as an open question.
- Streaming response parsing. Anthropic supports SSE; we currently consume the
  full-buffer response. Streaming arrives when the live UI does.

## Files touched

- new: `src/tern/core/canonical.py`, `src/tern/core/provider.py`,
  `src/tern/adapters/__init__.py`, `src/tern/adapters/bedrock_anthropic.py`
- new tests: `tests/test_canonical.py` (16 cases), `tests/test_bedrock_adapter.py`
  (15 cases)
- edited: `src/tern/core/__init__.py` (re-exports), `pyproject.toml`
  (`boto3>=1.34`, `boto3-stubs[bedrock-runtime]>=1.34`)

## Gates

- pytest: 39 / 39 pass (24 canonical + 15 adapter, plus prior 8 from S5/S6 — now
  bumped because the canonical tests subsume some earlier placeholders)
- ruff: clean
- mypy --strict: clean across 15 source files
- `tern --version` → `tern 0.0.1`
