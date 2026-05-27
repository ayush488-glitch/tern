---
title: M11 — observability
type: concept
created: 2026-05-27
updated: 2026-05-27
sources: [decisions/adr-0002-runtime-shape.md, decisions/adr-0005-session-state.md]
tags: [tern, observability, m11, span, ndjson, recorder]
---

# M11 — observability

## What it is
M11 turns the TurnEvent stream (defined by [ADR-0002](../decisions/adr-0002-runtime-shape.md)) into a span tree on disk and a pretty-printed view. It's the FIRST module to land — every later module ships with observability already wired.

## Files (S6)
```
src/tern/core/events.py     TurnEvent vocabulary — 11 event classes, frozen+slots
src/tern/obs/paths.py       TERN_HOME, sanitize_cwd, project_dir, spans_path
src/tern/obs/span.py        Span (open/closed pair), label, total_cost_usd
src/tern/obs/sink.py        NDJSONSpanSink — append-only, stable-JSON, fsync-per-write
src/tern/obs/recorder.py    SpanRecorder — pair openers/closers, build forest
src/tern/obs/render.py      rich.tree.Tree renderer + forest_to_str (test-friendly)
src/tern/obs/replay.py      reload events from .ndjson, rebuild SpanRecorder
src/tern/cli.py             `tern spans <session>` command
tests/test_obs.py           5 tests; pairing, open spans, ndjson roundtrip, render, isolation
```

## The three contracts
1. **Pair shape** — every opener event has exactly one closer, matched by `call_id` when present, by kind otherwise. Recorder is best-effort; if the stream ends mid-pair the span stays open.
2. **Singleton shape** — events with no closer (TurnCompleted, UserAborted, ReflectionTriggered) become closed spans with opener==closer. Uniform tree.
3. **Sink shape** — one ndjson line per event, stable JSON (`sort_keys=True, separators=(",",":")`). The sink is the system of record; the span tree is a derived view.

## How it lifts ADR-0002
ADR-0002 specified the event vocabulary. M11 is the first consumer that proves the vocabulary is sufficient for end-to-end observability without LLM-specific knowledge. The recorder special-cases nothing; new event pairs (e.g. `NetworkRequested`/`NetworkReturned` later) need only a new entry in `events._OPENERS`.

## How it lifts ADR-0005
The ndjson sink lives at `~/.tern/projects/<sanitized-cwd>/spans/<session>.ndjson`. Same path scheme as turn-objects (`objects/`) and refs (`refs/`). When ADR-0005's object store lands at S10, it slots in alongside, no relayout.

## Pitfalls
- ❌ Don't fake closers if a stream ends mid-pair. Leave the span open. The tree shows `(open)` instead of a fake duration.
- ❌ Don't sort/reorder events on read. Sequence matters; chronological order is invariant.
- ❌ Don't skip the sink in tests. NDJSON roundtrip is the regression net for schema evolution.

## Future work
- M11 + cost-routing (D1, ADR-0004): `RoutingPolicy.pick(...)` reads `LLMResponded.cost_usd` aggregated per session for back-pressure decisions.
- Streaming token events (deferred to S15 TUI polish): the event shape supports it; the recorder folds streamed deltas into one Span.
