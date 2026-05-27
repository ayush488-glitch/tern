---
title: S7 — M4 canonical messages and Bedrock-Anthropic adapter
type: session
created: 2026-05-27
updated: 2026-05-27
sources: []
tags: [tern, session, s7, m4, canonical, provider-adapter, bedrock, tdd]
---

# S7 — M4 canonical messages + Bedrock-Anthropic adapter

## Goal

Install the lock: a vendor-neutral canonical message log + the first concrete
adapter that translates to and from a real provider wire format. Pure functions
at the edge, frozen dataclasses in the core. TDD throughout.

## What we built

### Code
- `src/tern/core/canonical.py` (~210 LOC) — frozen dataclasses, `stable_json`,
  `content_hash`, `from_json`. `SCHEMA_VERSION = 1`.
- `src/tern/core/provider.py` (~55 LOC) — `ProviderAdapter` Protocol
  (runtime-checkable; siblings, not subclasses).
- `src/tern/adapters/__init__.py` — package marker.
- `src/tern/adapters/bedrock_anthropic.py` (~230 LOC) — first adapter. Pure
  `to_wire`, pure `from_wire`, side-effecting `complete`.
- `src/tern/core/__init__.py` updated to re-export the canonical types.

### Tests
- `tests/test_canonical.py` (16 cases): frozen invariants, hash stability, byte-stable
  JSON, schema version stamping, JSON roundtrip per block type, `Capabilities` defaults,
  `ProviderResponse` shape, `ToolSpec` shape.
- `tests/test_bedrock_adapter.py` (15 cases): system lifting, role mapping, tool_use
  / tool_result mapping, image mapping, cache_breakpoints, ToolSpec bare wrapping
  (NOT OpenAI function wrapper), from_wire response parse, full canonical→wire→canonical
  roundtrip, `complete()` calls boto3 (mocked).

### Deps
- `boto3>=1.34` added to `[project.dependencies]`.
- `boto3-stubs[bedrock-runtime]>=1.34` added to `[project.optional-dependencies.dev]`.

### Wiki
- `wiki/concepts/m4-canonical-messages.md` (new)
- `wiki/index.md` updated to point at the new concept page
- `wiki/roadmap/14-session-plan.md` — S7 ✅, ▶ moves to S8
- `wiki/log.md` — session-end appended

## TDD rhythm

Two RED→GREEN cycles, no production code without a failing test first:

1. write `test_canonical.py` → `pytest` → ModuleNotFoundError (canonical) ✅ RED
2. implement `core/canonical.py` → `pytest` → 16/16 ✅ GREEN
3. write `test_bedrock_adapter.py` → `pytest` → ModuleNotFoundError (adapters) ✅ RED
4. implement `adapters/__init__.py` + `adapters/bedrock_anthropic.py` → `pytest` → 15/15 ✅ GREEN

The adapter passed all 15 tests on the first GREEN attempt. That's the value of
writing the wire-format spec into the test before writing the translator.

## Decisions made (and why)

- **Frozen dataclass, not pydantic, for canonical types.** Hashing is free with
  dataclass + `frozen=True, slots=True`. Pydantic v2 re-validates on every construct,
  and we construct a CanonicalMessage on every turn. Pydantic stays scoped to
  `ToolSpec` JSON-schema generation in M5 where its `.model_json_schema()` carries
  weight.
- **`content` is a tuple, not a list.** Lists aren't hashable; we need cheap and
  deterministic content addressing for D3.
- **`ProviderAdapter` is a Protocol.** ADR-0004 §rejected-A: shared logic across
  vendors is approximately zero. A base class either ends up empty or becomes a
  god-conditional.
- **`to_wire` / `from_wire` are pure static methods.** This is what makes adapter
  tests offline and what makes replay deterministic. The only side effect lives in
  `complete()`.
- **`stable_json` uses `sort_keys=True, separators=(",",":")`.** Byte-identical across
  Python versions and `PYTHONHASHSEED` values. No spaces. `content_hash` depends on
  this contract; tests pin it.
- **System messages lift to top-level `system` field.** Anthropic Messages API doesn't
  accept system in `messages[]`. We concatenate multiple system messages with `\n\n`.
- **ToolSpec wraps BARE on Anthropic.** `{name, description, input_schema}`. The
  OpenAI-style `{"type":"function","function":{...}}` wrapper is exactly what's
  breaking Kimi K2.5 on Bedrock today (per token-cost-master pitfall). Adapter-per-
  vendor is the right answer; one shape doesn't fit.

## Pitfalls hit during the session

- `Union[A, B]` plus `from __future__ import annotations` triggered ruff UP007.
  Switched to PEP 604 `A | B`. Free.
- Pyright disagreed with mypy on `cls(**d)` return type when factory looks up by `kind`.
  Mypy --strict was happy; dropped the speculative `# type: ignore`.
- `boto3` ships no `py.typed` marker. Mypy --strict refuses untyped imports.
  Fix: `boto3-stubs[bedrock-runtime]>=1.34` in dev extras. `uv sync --extra dev`
  pulled `types-awscrt` and `types-s3transfer` transitively.
- `bare pytest` still doesn't find the project venv on macOS — must use
  `uv run pytest`. Same for `mypy`, `ruff`. Documented again in muscle memory.

## Gates at session end

```
pytest:           39/39 ✅   (24 canonical + 15 adapter)
ruff check:       clean ✅
mypy --strict:    clean ✅   (15 source files)
tern --version:   tern 0.0.1 ✅
```

## What's next (S8)

S8 picks up M3 (the agent turn loop) and the D1 routing skeleton:

- `src/tern/core/turn.py` — `TurnPurpose` enum, `Turn` dataclass.
- `src/tern/core/routing.py` — selector that returns a `ProviderAdapter` based on
  turn purpose. Initial policy: arch/security → Opus, default code → Sonnet,
  lint/format → Haiku, boilerplate → Nova Micro. Mirrors the token-cost-master
  routing tree.
- First end-to-end live `complete()` against Bedrock, gated behind an env flag
  (no live calls in CI).
- Extend the agent loop scaffold to consume the canonical message log built in S7.

We do NOT add a second adapter (OpenAI / Anthropic-direct) until S9 — finishing one
provider end-to-end first beats stubbing two halfway.

## Handoff state

- Working dir: `/Users/ayushsingh/Desktop/coding-agent`
- All four gates green at session boundary.
- Tree must be clean after the closing commit (`session: S7 — M4 canonical
  messages + Bedrock-Anthropic adapter`).
- `.scratch/` empty for this session — no parking-lot notes.
