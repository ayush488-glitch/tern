---
title: "ADR-0002 — Runtime shape (turn loop)"
type: decision
created: 2026-05-27
updated: 2026-05-27
status: accepted
supersedes: []
superseded_by: []
tags: [tern, runtime, turn-loop, m1, m3, phase-1]
---

# ADR-0002 — Runtime shape (turn loop)

## Status
Accepted, 2026-05-27.

## Context

[ADR-0001](adr-0001-jtbd-and-scope.md) commits Tern to a synchronous, approval-gated, full-surface coding agent. The runtime shape — what a "turn" is, how steps compose, how state evolves — is the spine the rest of the architecture hangs off. Get this wrong and every later module (tools, provider, session) ends up papered over with workarounds.

Three concrete questions to answer:

1. **Imperative loop or async generator?** Both describe the same control flow; only one composes well.
2. **Mutable state or state-replaced?** Mutable is easy at first, expensive forever (replay, branching, observability all need pure deltas).
3. **What ends a turn?** Step cap, budget, error class, "done" signal — multiple terminators, all need to be honest.

Prior art: claude-code (TS) ships an async generator with `state-replaced` at every continue site (see [ref-claude-code](../sources/ref-claude-code.md)). aider (Python) uses a synchronous while-loop with mutable session state and reflection retries (see [ref-aider](../sources/ref-aider.md)). Both work; only the first survives D1 (per-turn cost routing) and D3 (replay/branch) without surgery.

## Decision

### A turn is an async generator
A turn yields a stream of `TurnEvent`s — `LLMRequested`, `LLMResponded`, `ToolCalled`, `ToolReturned`, `ApprovalRequested`, `ApprovalGranted`, `ReflectionTriggered`, `TurnCompleted`. The TUI (M2) consumes the stream and renders. The session store (M7) consumes the stream and persists. Tests consume the stream and assert.

```python
async def run_turn(
    state: TurnState,
    *,
    adapter: ProviderAdapter,
    tools: ToolRegistry,
    max_steps: int = 25,
) -> AsyncIterator[TurnEvent]:
    while not state.is_terminal:
        state = state.advance()  # state-replaced, never mutated
        async for event in step(state, adapter, tools):
            yield event
            state = state.fold(event)
```

Single generator. Single contract. Every consumer (TUI, store, tests, future replay player) reads the same stream.

### State is replaced, not mutated
`TurnState` is a frozen dataclass. Every advance produces a new instance. The previous instance stays referenceable (M7 hashes it; replay walks it). Mutation is forbidden; structural sharing keeps memory honest.

```python
@dataclass(frozen=True, slots=True)
class TurnState:
    canonical_log: tuple[CanonicalMessage, ...]
    pending_tool_calls: tuple[ToolCall, ...]
    step_count: int
    max_steps: int
    parent_hash: str
    is_terminal: bool

    def fold(self, event: TurnEvent) -> "TurnState":
        # pure function, returns new TurnState
        ...
```

This is the lock that makes D3 (replay/branch) cheap. Every state is content-addressable; every parent pointer is a hash; "branch from turn 7" is one struct copy with a new parent.

### Termination is multi-source, ranked
A turn ends when ANY terminator fires, in this priority order:

1. **`done` signal** from the model (assistant-turn with no tool calls and no reflection trigger).
2. **`max_steps` cap** (default 25; configurable per command via M0).
3. **User abort** (Ctrl+C → `TurnEvent.UserAborted`; partial state still persisted).
4. **Permission denial** that the agent cannot recover from (M5 surfaces `ToolDenied`; agent decides retry-with-different-args or terminate).
5. **Provider error after retry exhaustion** (M4 + M12 together).

No `$ budget` terminator at the runtime level. ADR-0001 ruled out hard cost ceilings. Cost is reported per-turn by M11 and influences D1 routing; it does not abort the turn.

### Reflection retry is part of the loop, not a wrapper
When a tool returns a parse error, lint error, or test failure, the result feeds back as the NEXT turn's first user message — exactly aider's pattern, lifted verbatim ([ref-aider](../sources/ref-aider.md) §5). Implemented as a `ReflectionTriggered` event followed by a synthetic `CanonicalMessage(role="user", content=...)`.

Reflection has its own counter (`reflection_depth`, default cap 3). Once a reflection chain itself fails 3 times, the turn surfaces the failure to the user; it does not silently grind.

### Sub-agents run the same shape
Browser-use's `agent.run()` (D5, M9) and any future spawn-a-helper-agent flow are a single tool call from the parent's perspective. The parent doesn't see the sub-agent's steps; it sees one `ToolReturned` event with the rolled-up `ActionResult`. The sub-agent contract is settled at the M5 boundary, not the M1 boundary. See [ADR-0003](adr-0003-tool-surface.md) for the contract details.

This means M1 stays simple — one loop, one event stream, one termination policy — even with arbitrarily deep sub-agent trees.

## Alternatives rejected

### A. Synchronous while-loop with mutable state (aider-style)
Works for one user, one provider, single-terminal-tail UI. Breaks immediately for:
- D1 (cost routing) — can't snapshot state cheaply for what-if model swap.
- D3 (replay/branch) — mutable state has no past tense.
- Concurrent TUI rendering — textual wants a stream, not polling.
- Test ergonomics — assertions on side effects vs assertions on yielded events.

Aider's reflection retries are great; we lift those. Their loop shape we don't.

### B. Reactive / observable-stream library (RxPy, AnyIO streams)
Adds a dependency and a vocabulary that nobody on the team owns reflexively. `async generator` is built-in and gives 95% of the benefit. Rejected for surface-area cost.

### C. Actor model (one actor per role: planner, executor, reviewer)
Tempting and over-engineered. Adds inter-actor protocol, mailboxes, supervision trees — all problems we don't have. The async generator is one actor; sub-agents are nested generators. Promote to actors only if a concrete need shows up (it won't in v1).

### D. `$ budget` terminator
ADR-0001 rejected hard cost ceilings. Cost-per-turn is observable (M11) and influences routing (D1). It is NOT a runtime terminator. The user owns the bill; the runtime owns honesty.

## Consequences

### Positive
- One event stream, every consumer reads from it. No "one shape for the TUI, another for the persister."
- State-replaced means hashing, replay, and branching all become trivial structural operations.
- Reflection-as-event keeps the loop honest: every retry is auditable, capped, and visible to M11.
- Sub-agent contract at M5 keeps M1 simple even at depth.

### Negative / accepted costs
- async generators are slightly harder to reason about than while-loops. We pay this in onboarding docs and in the walkthrough chapter for S8.
- Frozen dataclasses with structural sharing have a learning curve for contributors used to mutable Python idioms. Mitigated with `state.advance()` / `state.fold(event)` helpers and tests that assert state invariance.
- Termination logic spread across event handlers needs a single decision table to stay sane. We file `concepts/termination-decision-table.md` in S8 when implementation lands.

### Open questions deferred
- Concurrent tool calls (parallel `ToolCalled` events) — supported in event shape, not in v1 scheduler. Single-flight in M5; parallelism is a future ADR.
- Mid-turn provider swap (D1 routing changes between steps) — possible because state is canonical; deferred to S7 implementation.
- Streaming token-level events (yielding partial assistant content) — deferred to TUI polish (S15).

## References
- [ADR-0001 jtbd-and-scope](adr-0001-jtbd-and-scope.md) — anchor.
- [ADR-0003 tool-surface](adr-0003-tool-surface.md) — sub-agent contract sits at M5.
- [ADR-0004 provider-layer](adr-0004-provider-layer.md) — canonical messages flow through this loop.
- [ADR-0005 session-state](adr-0005-session-state.md) — frozen state hashes are turn objects.
- [canonical-message-log](../concepts/canonical-message-log.md) — the lock this loop only ever sees.
- [ref-claude-code](../sources/ref-claude-code.md) — async generator + state-replaced lifted from here.
- [ref-aider](../sources/ref-aider.md) — reflection retry loop lifted from here.
