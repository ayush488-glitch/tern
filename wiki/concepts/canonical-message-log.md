---
title: Canonical message log (the lock)
type: concept
created: 2026-05-27
updated: 2026-05-27
sources: [../sources/ref-claude-code.md, ../sources/ref-aider.md, ../sources/wiki-llmops-synthesis.md]
tags: [tern, m4, lock, canonical, provider]
---

# The lock — canonical message log ≠ provider wire format

Every other design decision in Tern hangs on this one invariant:

> **Internal canonical message log ≠ provider wire format.**
> Two pure functions translate. Everything else follows.

## What it means

Tern stores conversations in a vendor-neutral schema (`CanonicalMessage`, `ContentBlock`, `ToolSpec`). The agent core (M3) only ever reads or writes canonical. When it's time to call a model, M4's `ProviderAdapter` runs `canonical → wire` (serialize). When the response comes back, the adapter runs `wire → canonical` (parse). Both functions are pure, side-effect-free, and roundtrip-tested.

```
[M3 agent core]  ──(canonical)──>  [M4 adapter]  ──(wire)──>  [provider HTTP]
[M3 agent core]  <──(canonical)──  [M4 adapter]  <──(wire)──  [provider HTTP]
```

## Why it's THE lock
- **D1 (cost routing)** needs to swap providers per turn. Only possible if storage is provider-neutral.
- **D3 (replay/branch)** needs to re-feed past turns into possibly different providers. Only possible if storage is provider-neutral.
- Adding a provider = one new file (one adapter). No core changes, no cross-cutting refactor.
- Tool-schema shapes diverge: Anthropic bare `{name, description, input_schema}`, OpenAI wrapped `{type:"function", function:{...}}`, Bedrock-Kimi expects OpenAI-style. The adapter normalizes. The core never sees provider quirks.

## What it forbids
- ❌ `BaseProviderAdapter` with shared logic. Adapters are siblings, not subclasses. They share only the canonical type.
- ❌ Storing Anthropic-shaped messages because "we use Anthropic." That couples M3 to one vendor and breaks D1 + D3.
- ❌ Serializing canonical with anything but stable JSON: `json.dumps(sort_keys=True, separators=(",",":"))`. Hash stability matters for D3.
- ❌ Pickle. Schema-versioned canonical JSON only; additive evolution.

## Where it lives in code (planned)
```
src/tern/
  core/
    canonical.py        # CanonicalMessage, ContentBlock, ToolSpec — frozen dataclasses
    provider.py         # ProviderAdapter Protocol
  adapters/
    bedrock_anthropic.py
    openai.py           # later
    litellm.py          # later (one backend, not the abstraction)
```

## Tests that prove it
- `roundtrip(canonical → wire → canonical) == canonical` for every adapter.
- Same canonical input + 2 adapters produces semantically equivalent prompts.
- `hash(canonical_json(turn))` is stable across Python versions, dict ordering, runs.

## Prior art
- Aider doesn't have this. Aider's `Model` class hard-codes per-model edit-format and capability flags (models.py L438-510); they call litellm directly. That's why D1-style routing is impossible to retrofit there.
- Claude Code (TS) has a partial version: provider abstraction exists, but state replacement happens at the provider boundary, not at a vendor-neutral core layer.
- Tern goes further: canonical IS the system of record. Adapters are I/O.

See [14-modules](14-modules.md), [architecture.html](../../docs/architecture.html), and the future [adr-0004-provider-layer.md](../decisions/adr-0004-provider-layer.md).
