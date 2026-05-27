---
title: S6 — M11 observability skeleton
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [tern, session, m11, observability, span]
---

# S6 — M11 observability skeleton

Built M11 in one session. Eight files (~700 LOC source + ~150 LOC tests). Eight tests, four gates green.

See concept page: [m11-observability](../concepts/m11-observability.md).

## What landed

```
src/tern/core/events.py            event vocabulary (TurnEvent union, 11 classes)
src/tern/obs/paths.py              TERN_HOME, project_dir, spans_path
src/tern/obs/span.py               Span dataclass (open/closed pair)
src/tern/obs/sink.py               NDJSONSpanSink (append-only, stable JSON)
src/tern/obs/recorder.py           SpanRecorder (pair matching, forest building)
src/tern/obs/render.py             rich.tree renderer
src/tern/obs/replay.py             rebuild events from .ndjson
src/tern/cli.py                    `tern spans <session>` command added
tests/test_obs.py                  5 tests (pairing, open-spans, roundtrip, render, cwd isolation)
```

`pyproject.toml` gained `pydantic>=2.7` (will be used at S7 by canonical messages).

## Gates green
```
pytest -q          → 8 passed (3 smoke + 5 obs)
ruff check         → All checks passed
mypy --strict      → no issues found in 11 source files
tern --version     → tern 0.0.1
tern spans X       → graceful "no span file at..."
```

## Decisions made during S6 (small, none changed an ADR)
- Span pair-matching uses `call_id` when present (tools, approvals), else opener-kind. Same shape across all three pair types — recorder doesn't fork.
- Singleton events (`TurnCompleted`, `UserAborted`, `ReflectionTriggered`) become closed-spans with `opener==closer`. Uniform tree.
- `TERN_HOME` env var overrides `~/.tern/`. Tests set it to a tmp dir per case.
- Sanitized cwd scheme mirrors claude-code's: replace path separators with hyphens. Idempotent.
- ndjson sink fsyncs per write (correctness > throughput at this layer; we'd rather lose perf than the audit trail).

## What's NOT in S6 (deferred)
- Cost aggregation across sessions — only per-tree right now. Deferred to S10 (D1 router lands).
- Streaming events (token-by-token) — vocabulary supports, no consumer yet. Deferred to S15.
- Rebuild-on-corruption / `tern rebuild-index` — ADR-0005 §open. Lives with the object store at S10.

## Pitfalls hit (and resolved)
- Initial Typer CLI hung when no subcommand — fixed in S3 already. CLI wiring at S6 reused the `--version` callback pattern.
- mypy strict + dataclasses-with-default-factory needed slightly different pattern than I expected — `field(default_factory=_gen_id)` with `Literal` kind discriminator. Logged for the walkthrough chapter.
- ruff B008 fights Typer's `typer.Option(...)` defaults — added to `ignore` in pyproject.

## Handoff — S7
Next session = **S7 M4 canonical messages + first adapter (Bedrock-Anthropic)**.

What S7 needs from S6:
- `LLMRequested`/`LLMResponded` events are already defined and emit ready-to-consume cost fields. S7's adapter only has to fill them in.
- M11 spans will instrument the very first real Bedrock call automatically — no extra wiring.

What S7 will produce:
- `src/tern/core/canonical.py` — `CanonicalMessage`, `ContentBlock` family, `ToolSpec`, `Cost`, `Capabilities`, `ProviderResponse`.
- `src/tern/core/provider.py` — `ProviderAdapter` Protocol.
- `src/tern/adapters/bedrock_anthropic.py` — `to_wire`/`from_wire`/`complete`. Uses boto3.
- `tests/test_canonical.py` — frozen-hash stability, JSON-roundtrip, schema-version stamping.
- `tests/test_bedrock_adapter.py` — pure `to_wire`/`from_wire` (no live calls); roundtrip tests.

Read for S7: AGENTS.md → wiki/index.md → roadmap/14-session-plan.md (▶ S7) → this S6 page → ADR-0004 (the spec) → ADR-0002 (event vocabulary M4 emits into).
