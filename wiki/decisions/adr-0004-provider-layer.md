---
title: "ADR-0004 — Provider layer and cost router (D1)"
type: decision
created: 2026-05-27
updated: 2026-05-27
status: accepted
supersedes: []
superseded_by: []
tags: [tern, provider, canonical, cost-router, d1, m4, phase-1]
---

# ADR-0004 — Provider layer and cost router (D1)

## Status
Accepted, 2026-05-27.

## Context

This ADR cashes the lock written into [canonical-message-log](../concepts/canonical-message-log.md): internal canonical message log ≠ provider wire format. Two pure functions translate. Now we specify exactly what the canonical log looks like, what `ProviderAdapter` requires, how the first adapter (Bedrock-Anthropic) works, and what shape the cost router (D1) takes at v0.

Three concrete questions:

1. **What's in `CanonicalMessage`?** Roles, content blocks, tool calls, tool results, metadata.
2. **What's the `ProviderAdapter` contract?** What inputs, what outputs, what side-effects allowed.
3. **What does D1 actually do at v0?** ADR-0001 said quality first, route downward only when provably cheap. What's "provably cheap" mean operationally?

Prior art:
- aider hard-codes `ModelSettings` per model with edit-format + capability flags ([ref-aider](../sources/ref-aider.md)). No D1-equivalent. Calls litellm directly.
- claude-code has a provider boundary but state replacement happens there, not in a vendor-neutral core ([ref-claude-code](../sources/ref-claude-code.md)).
- MCP, Anthropic, OpenAI, Bedrock all use slightly different tool-call shapes (bare vs `{type:"function", function:{}}` wrapper); known Hermes-Bedrock-Kimi failure mode (see token-cost-master skill pitfalls).

## Decision

### Canonical message log — frozen, hashable, additive
```python
@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: tuple[ContentBlock, ...]
    metadata: Metadata               # provenance, ts, model_id, cost, seed

@dataclass(frozen=True, slots=True)
class TextBlock:
    kind: Literal["text"] = "text"
    text: str

@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    kind: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    args: dict[str, Any]            # validated upstream by Tool's pydantic schema

@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    ok: bool
    content: str
    error: str | None
    metadata: dict[str, Any]

@dataclass(frozen=True, slots=True)
class ImageBlock:
    kind: Literal["image"] = "image"
    media_type: str                 # "image/png", "image/jpeg"
    data_b64: str

ContentBlock = TextBlock | ToolCallBlock | ToolResultBlock | ImageBlock
```

Properties:
- **Frozen + hashable**: every message has a stable hash. Turn-object content addressing (D3, see [ADR-0005](adr-0005-session-state.md)) depends on this.
- **Additive evolution**: new ContentBlock subclasses are allowed; old ones never change shape. Schema version stamped in `Metadata`.
- **Stable JSON**: `json.dumps(asdict(msg), sort_keys=True, separators=(",",":"))`. No pickle.
- **No vendor types**: nothing here references Anthropic, OpenAI, or Bedrock.

### `ProviderAdapter` Protocol
```python
class ProviderAdapter(Protocol):
    name: str                       # "bedrock-anthropic" | "openai" | "anthropic"
    model_id: str                   # "anthropic.claude-sonnet-4-20250514-v1:0"
    capabilities: Capabilities      # tool_use, vision, max_input_tokens, supports_caching

    async def complete(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> ProviderResponse:
        ...

    @staticmethod
    def to_wire(messages: tuple[CanonicalMessage, ...]) -> Any: ...   # canonical → provider
    @staticmethod
    def from_wire(response: Any) -> CanonicalMessage: ...             # provider → canonical
```

Both `to_wire` and `from_wire` are pure functions. Roundtrip-tested per adapter. Adapters are SIBLING implementations, not subclasses of a `BaseProviderAdapter` (rejected — see Alternatives). They share only the Protocol.

### v0 adapter — Bedrock-Anthropic
First adapter ships in S7. Lives at `src/tern/adapters/bedrock_anthropic.py`.

Responsibilities:
- Map canonical roles → Anthropic Messages API. System prompt extracted to top-level `system:`. User/assistant/tool messages mapped 1:1.
- Map canonical `ToolCallBlock` → Anthropic `tool_use` block. Map canonical `ToolResultBlock` → Anthropic `tool_result` block.
- Map `ToolSpec` (Tern's pydantic-generated JSON schema, see [ADR-0003](adr-0003-tool-surface.md)) → Anthropic's bare `{name, description, input_schema}` shape.
- Apply cache breakpoints (system, exemplars, repo_map, done). Lifted from claude-code + aider patterns.
- Handle Bedrock's auth via boto3 (existing creds in `~/.zshrc`).

Future adapters (S10+):
- `openai.py` — wraps tool calls in `{type:"function", function:{}}` shape. Different system-prompt placement.
- `litellm.py` — ONE backend (covers OpenRouter, Anthropic-direct, Vertex), not THE abstraction. Used when target provider has no first-party adapter yet.

Tooling rule: **if a target provider has a first-party SDK with reasonable types, write the adapter directly. Use litellm only as fallback.** Aider's coupling to litellm is the failure mode we're explicitly avoiding.

### D1 — cost router v0
Cost router is a function from `(turn_purpose, state) → adapter`. v0 is rule-based, opinionated, frontier-first.

```python
class RoutingPolicy:
    def pick(self, purpose: TurnPurpose, state: TurnState) -> ProviderAdapter:
        ...

class FrontierFirstPolicy(RoutingPolicy):
    """v0 default. ADR-0001 quality-first posture."""
    def pick(self, purpose, state):
        if purpose in {SCAFFOLD, FORMAT, RENAME, BOILERPLATE}:
            return self.cheap     # Haiku-class
        if purpose == ARCHITECT:
            return self.deep      # Opus-class
        return self.default       # Sonnet-class for the 80%
```

Rules:
- **Default = frontier (Sonnet-class).** Most turns route here.
- **Architect / security / hard-debug → deep (Opus-class).** Tagged manually via slash command (`/think hard`) or detected by purpose annotations on the WorkTask (M3).
- **Provably cheap → cheap (Haiku-class).** Lint, format, scaffold, rename, autocomplete. Detection is rule-based, NOT model-routed (you don't burn a frontier call to decide whether to use a cheap one).
- **No automatic downgrade on cost.** Cost is reported; the user sees the bill via M11.

Future v1 (post-v1, not S5): purpose-tagging via lightweight classifier, A/B testing of routes, learned policy. v0 stays rule-based and inspectable.

### Tool-spec normalization — the Anthropic-vs-OpenAI shape gotcha
Different providers want tools in different shapes. Tern's canonical `ToolSpec` is provider-neutral (name, description, JSON schema). Each adapter applies the wrapper:

- Anthropic: `{name, description, input_schema}` — bare.
- OpenAI: `{type: "function", function: {name, description, parameters}}` — wrapped.
- Bedrock-Anthropic: same as Anthropic.
- Bedrock-Kimi (if/when): wrapped (OpenAI-style). Known failure mode in Hermes; we get this right because the adapter applies the wrapper, not the core.

The agent core never sees these shapes. ToolSpec is canonical; wrapping is adapter responsibility.

### Caching — explicit, additive
Adapters that support prompt caching (Anthropic, Bedrock-Anthropic) accept `cache_breakpoints: tuple[int, ...]` — message indices after which to mark a cache breakpoint. Tern's prompt builder produces breakpoints at the natural seams (system, examples, repo_map, done) — same `ChatChunks` pattern as aider, but cached at canonical-index level not litellm-level.

### Where this lives
```
src/tern/
  core/
    canonical.py              # CanonicalMessage, ContentBlock, ToolSpec
    provider.py               # ProviderAdapter Protocol, ProviderResponse, Capabilities
    routing.py                # RoutingPolicy, FrontierFirstPolicy, TurnPurpose
  adapters/
    bedrock_anthropic.py      # v0
    openai.py                 # later
    litellm.py                # last-resort
```

## Alternatives rejected

### A. `BaseProviderAdapter` abstract class
The shared logic across Anthropic, OpenAI, Gemini, and litellm is approximately zero (different auth, different message shapes, different streaming, different tool-wrapping, different system-prompt placement). A base class either ends up empty or becomes a god-conditional. Sibling Protocol implementations stay honest. (Same reasoning rejected `BaseTool` in [ADR-0003](adr-0003-tool-surface.md).)

### B. litellm as THE provider abstraction
Aider's path. The cost: every provider quirk (tool-shape, caching, streaming) leaks through litellm's lowest-common-denominator interface, and Tern can never fully use any provider's strengths. litellm is fine as ONE backend (covers exotic providers we don't want to write directly). It is not the abstraction.

### C. Auto-downgrade on cost threshold
ADR-0001 ruled this out. It puts D1 in degraded mode by default; bad turns cost hours, not cents. v0 is frontier-first. Users get the bill; users decide.

### D. Learned routing policy in v1
Tempting, premature. We don't have the data, the labels, or the eval harness. Rule-based policy is inspectable, debuggable, and ships in S7.

### E. Pickled / msgpack canonical messages
Pickle is unsafe across versions; msgpack adds a dep. JSON with sort_keys is portable, hashable, human-readable, and good enough. Schema versioning via `Metadata.schema_version` handles evolution.

### F. `BaseMessage` from langchain-style ecosystems
External shape pulls in dependencies and concepts we don't want (callbacks, runnables, outparsers). We define our own canonical shape; it's 200 lines of frozen dataclasses; we own it.

## Consequences

### Positive
- D1 is a real architectural commitment, not a feature flag. Every turn picks its adapter.
- Adding a provider = one new file (one adapter). No core changes.
- Tool-shape gotchas (Bedrock-Kimi-style) live in adapters; the core stays pristine.
- Roundtrip-testable. Hash-stable. Reusable across replay/branch (D3).

### Negative / accepted costs
- Writing a new adapter requires understanding the target provider's quirks. We don't get litellm-style "it just works for everything." The trade is intentional.
- Prompt caching is per-adapter logic. We pay this in code per provider that supports caching. Worth it.
- Pydantic-derived JSON Schema doesn't 1:1 match every provider's preferred schema dialect. Adapter `to_wire` may need to massage (e.g. drop `$schema`, flatten `$defs`). Acceptable.

### Open questions deferred
- Streaming token events through canonical → ProviderResponse — supported in shape, not in v1 default flow. Lands with TUI polish (S15).
- Mid-turn provider swap (one step Sonnet, next step Haiku) — supported by canonical; deferred to v1.1 routing policy.
- Image content blocks in M9 (browser screenshots fed back) — supported in `ImageBlock`; full plumbing in S13.
- Cost-per-token table — lives outside the adapter (in `routing.py` or a config); decide in S7 implementation.

## References
- [ADR-0001 jtbd-and-scope](adr-0001-jtbd-and-scope.md) — anchor (no cost ceiling, quality first).
- [ADR-0002 runtime-shape](adr-0002-runtime-shape.md) — canonical messages flow through this loop.
- [ADR-0003 tool-surface](adr-0003-tool-surface.md) — `ToolSpec` is the canonical input to adapters' tool-list.
- [ADR-0005 session-state](adr-0005-session-state.md) — canonical messages become turn-object content blocks (content-addressed).
- [canonical-message-log](../concepts/canonical-message-log.md) — the lock this ADR cashes.
- [differentiators](../roadmap/differentiators.md) — D1 lives here.
- [ref-aider](../sources/ref-aider.md) — `ChatChunks` cache-breakpoint pattern, `ModelSettings` antipattern (we wrap, not litellm-direct).
- [ref-claude-code](../sources/ref-claude-code.md) — provider boundary precedent.
