---
title: "ADR-0005 — Session, state, replay, branch (D3)"
type: decision
created: 2026-05-27
updated: 2026-05-27
status: accepted
supersedes: []
superseded_by: []
tags: [tern, session, state, replay, branch, d3, m7, phase-1]
---

# ADR-0005 — Session, state, replay, branch (D3)

## Status
Accepted, 2026-05-27.

## Context

[ADR-0001](adr-0001-jtbd-and-scope.md) commits Tern to D3 — per-turn replay and branch, where any past turn can be re-run, forked, or A/B-compared. [ADR-0002](adr-0002-runtime-shape.md) made every `TurnState` frozen and hashable. [ADR-0004](adr-0004-provider-layer.md) made canonical messages stable-hashable. This ADR specifies the storage layer that turns those properties into a usable feature: how turns are persisted, how sessions resume, how branches fork, how replay verifies.

Three concrete questions:

1. **What's the storage shape?** Object store? Append-only log? SQLite? All three?
2. **What's a turn-object?** Hashed how, parented how, what's NOT in it.
3. **What does `tern resume` / `tern branch` / `tern log` actually do?**

Prior art:
- claude-code uses JSONL transcripts at `~/.claude/projects/<sanitized-cwd>/<uuid>.jsonl` ([ref-claude-code](../sources/ref-claude-code.md)). One file per session, append-only. No content-addressing, no branching.
- aider uses `commit_before_message` for per-edit git snapshots ([ref-aider](../sources/ref-aider.md)). One-way undo only; no per-turn graph.
- git itself: content-addressed object store + refs/branches. Battle-tested for exactly this shape of problem.

## Decision

### Storage = git-shaped object store + JSONL transcripts + SQLite index
Three layers, each with a different job:

```
~/.tern/
  projects/
    <sanitized-cwd>/
      objects/
        ab/
          ab12cd...                   # turn objects, content-addressed (sha256)
      refs/
        sessions/<uuid>               # current head of each session (a turn-object hash)
        branches/<uuid>/<name>        # named branches off a session
      sessions/
        <uuid>.jsonl                  # human-readable transcript (derived)
      index.sqlite                    # search/list queries; rebuildable from objects/
```

- **objects/** — system of record. Immutable. Content-addressed. Every turn-object is `objects/<sha[:2]>/<sha[2:]>`. Same layout git uses; stolen for the same reasons.
- **refs/sessions/** — one file per session, contents = current head turn-hash. Atomic update via tempfile + rename.
- **refs/branches/** — named branches off any turn-hash. `tern branch experiment-1 abc123def`.
- **sessions/<uuid>.jsonl** — append-only human-readable log derived from objects/. Exists because `tail -f`-able is irreplaceable for ops. NOT the system of record; rebuilds from objects/ on demand.
- **index.sqlite** — derived. Indexes `(session_id, turn_idx, parent_hash, model_id, cost, ts)` for fast `tern log`, `tern search`, etc. Rebuildable from objects/ via `tern rebuild-index`.

If `objects/` is intact, everything else can be reconstructed. If `objects/` is corrupt, the session is dead. Match git's semantics; pay git's robustness dividend.

### Turn-object schema
```python
@dataclass(frozen=True, slots=True)
class TurnObject:
    schema_version: int = 1
    parent: str | None                    # hash of parent turn-object; None = session root
    role: Literal["user", "assistant", "tool"]
    content: tuple[ContentBlock, ...]     # canonical, from ADR-0004
    tool_calls: tuple[ToolCallBlock, ...] # extracted for indexing
    tool_results: tuple[ToolResultBlock, ...]
    model_id: str | None                  # which adapter ran this turn (None for user/tool)
    routing_purpose: str | None           # ARCHITECT / DEFAULT / CHEAP — for D1 audit
    cost: Cost                            # tokens_in, tokens_out, dollars
    ts: int                               # ns since epoch
    seed: int | None                      # for replay determinism if provider supports it

# stable-JSON-hashed; hash IS the object name in objects/
```

Hash = `sha256(json.dumps(asdict(obj), sort_keys=True, separators=(",",":")).encode())`.

Properties:
- **`parent` is the only graph edge.** A session is a chain. A branch is a chain with a different head pointing into a shared past. Same as git's commit DAG.
- **No mutation, ever.** Turn-objects are immutable. Editing a turn = creating a new object with the new content + the same parent.
- **Everything is in `content`.** No side state. No "the assistant edited foo.py outside the log." Tool results are turn-objects too.

### Session lifecycle
- `tern run "..."` — opens (or resumes) a session at cwd. New session id allocated lazily on first turn-object write.
- Each turn produces 1+ turn-objects (user msg, assistant msg, possibly N tool turns). All share `parent` chain. Session ref advances after each.
- `tern resume [<session-id>]` — loads the head turn-object, walks parents, rebuilds canonical message log, hands to M1. If `<session-id>` omitted, picks most recent session in cwd.
- `tern log [<session-id>]` — reads from index.sqlite. Shows turn graph with timestamps, models, costs.
- `tern branch <name> [<turn-hash>]` — creates `refs/branches/<session>/<name>` pointing at `<turn-hash>` (default = current head). Future `tern run` on that branch advances ITS ref.
- `tern checkout <branch>` — switches active session ref.
- `tern diff <branch-a> <branch-b>` — shows divergence point and message-level diff downstream.

This vocabulary is git's, deliberately. Any user comfortable with git understands tern's session graph in 30 seconds.

### Replay semantics
Replay is the safety net for D3 and the foundation for evals.

```
tern replay <session-id>            # re-runs every turn from root, asserts hash equality
tern replay <session-id> --from N   # re-runs starting at turn N
tern replay <session-id> --model X  # re-runs but with a different adapter (hash WILL differ)
```

- **Pure replay** asserts `hash(replayed_turn) == hash(original_turn)` for every turn. Provider responses are loaded from objects/, NOT re-fetched. Used for: regression tests, debugging.
- **Live replay** re-fetches responses from the provider. Hashes will diverge (sampling, server-side updates). Used for: "what would happen now if I re-ran this conversation?" A/B testing.
- **Cross-model replay** (`--model X`) substitutes adapter on the fly. Cashes [ADR-0004](adr-0004-provider-layer.md): canonical messages are vendor-neutral, so re-feeding them to a different provider is well-defined.

### Branching semantics
Two flavors, both supported:

1. **Fork from a past turn**: `tern branch what-if abc123def`. Creates a new ref. Future runs on this branch start from `abc123def`'s state. Past is shared (object-store dedupes).
2. **Edit a past turn**: forbidden direct mutation; supported via "rewrite-and-continue." `tern rewrite <turn-hash>` opens an editor on the turn's user content, lets you change it, creates a NEW turn-object with the same parent and a NEW hash, rolls forward from there. The original chain still exists; you can `tern checkout` back to it.

Branching does NOT modify the user's repo / file system. Filesystem effects from a branched-away turn are NOT reverted automatically. Filesystem-level branching is git's job, not Tern's. We document the contract explicitly: "branching forks the conversation graph, not your workspace."

### Transcript format (sessions/<uuid>.jsonl)
One JSON object per line. Schema:
```json
{"turn": 7, "hash": "ab12...", "parent": "9f8e...", "role": "assistant",
 "content": [...], "model_id": "anthropic.claude-sonnet-4...", "cost": {...}, "ts": 1735...}
```
Append-only. `tail -f sessions/<uuid>.jsonl` works mid-run. NOT the system of record (objects/ is); the JSONL is a derived view.

### What's NOT in turn-objects
- ❌ Filesystem state. Tern's edits go to git in the user's repo. Tern's session store doesn't snapshot the repo.
- ❌ Adapter-specific wire format. ADR-0004's lock; we store canonical only.
- ❌ Live process state (textual widgets, mouse position). The TUI is a view; it rebuilds from turn-objects on resume.
- ❌ Secrets. M13 redacts before storage. Audit log lives elsewhere (`~/.tern/audit.log`, append-only, separate concern).

## Alternatives rejected

### A. Append-only JSONL only, no object store
What claude-code does. Simple, but no branching, no cross-session dedup, no content-addressing. To support D3 we'd need to retrofit an object store or fake one with line offsets — neither is cheaper than just doing the object store from the start.

### B. SQLite as system of record, JSONL derived
SQLite is great for indexing; lousy for object storage at the rates we need (one row per turn-object; lots of churn). Easier to corrupt than git-shaped objects/. Derived index ✓; primary store ✗.

### C. Raw git repo as the store (use real git plumbing)
Tempting; we get `git log`, `git checkout`, the whole UI for free. The cost: Tern sessions live INSIDE the user's working repo (or a sibling .git dir we manage), and any Tern operation entangles with the user's git state. Trust model gets confusing fast. Reject — we steal git's data shape, not git itself.

### D. Mutate turn-objects in place
Direct edit-history would be ergonomic. Breaks every D3 invariant: hashes drift, parents become unstable, replay becomes meaningless. The "rewrite-and-continue" pattern (new hash, same parent) is the right shape — exactly how git handles `git commit --amend` (it makes a new commit; the old hash isn't gone, just unreferenced).

### E. Store full filesystem snapshots in turn-objects
Would let Tern fully revert workspace state on branch. Storage cost is enormous; user's git already does this. Document the boundary; don't try to own filesystem semantics.

### F. Encrypted at rest by default
Adds key-management complexity. ADR-0001's trust model says user-machine, user-keys. The user's disk encryption is the user's; Tern doesn't add a second layer. M13 redaction handles secrets at write-time; that's the right layer. (Future: opt-in encryption for shared / synced session stores, post-v1.)

## Consequences

### Positive
- D3 is a real, working primitive — not a "log + diff" approximation.
- Replay gives us free regression tests for the agent itself.
- Cross-model replay turns sessions into evals: "run my last 50 sessions through Sonnet and Haiku, compare quality and cost."
- Object store dedups across branches; storage stays sane.
- `tern log / branch / checkout / diff` reuse vocabulary every developer already knows.

### Negative / accepted costs
- More code than just JSONL. ~500 LOC for the object store + refs + index. Acceptable; lifts cleanly into a single `src/tern/store/` module.
- Replay determinism is bounded by provider behavior. We hash inputs+seed; we cannot guarantee identical outputs from sampling models. Documented; pure-replay-only for hash equality.
- Workspace-vs-conversation branching split is non-obvious. README + walkthrough must be explicit: "tern branches forks the conversation; git branches forks your code."
- Index rebuild on corruption is not instant. For large sessions, `tern rebuild-index` is O(turns).

### Open questions deferred
- Garbage collection — orphaned objects (no ref points to them) accumulate. `tern gc` post-v1.
- Cross-machine sync — explicitly out of scope. Session store is local. Future: opt-in S3/git-remote sync.
- Object-store compression — turn-objects are small text; gzip on write later if storage matters.
- Multi-cwd sessions (work spans several repos) — v1 is per-cwd. Future ADR.
- Concurrent sessions on same cwd — supported (different uuids); no locking. May need a lock if `tern run` is invoked twice; deferred to S10 implementation.

## References
- [ADR-0001 jtbd-and-scope](adr-0001-jtbd-and-scope.md) — anchor.
- [ADR-0002 runtime-shape](adr-0002-runtime-shape.md) — frozen `TurnState` is the input to turn-objects.
- [ADR-0003 tool-surface](adr-0003-tool-surface.md) — `ToolResult` becomes the `content` of role=tool turn-objects.
- [ADR-0004 provider-layer](adr-0004-provider-layer.md) — canonical messages are what we hash and store.
- [canonical-message-log](../concepts/canonical-message-log.md) — the lock that makes cross-model replay tractable.
- [differentiators](../roadmap/differentiators.md) — D3 lives here.
- [ref-claude-code](../sources/ref-claude-code.md) — JSONL transcript pattern (we keep) + path scheme (we mirror at `~/.tern/...`).
- [ref-aider](../sources/ref-aider.md) — per-edit git snapshot (insufficient; D3 supersedes).
