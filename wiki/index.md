# Tern — wiki index

The catalog. Every wiki page is listed here with a one-line summary.
Update on every ingest, every filed query, every session end, every decision.

---

## Top-level
- [AGENTS.md](../AGENTS.md) — schema. How this wiki is structured and maintained.
- [log.md](log.md) — chronological ops log.
- [docs/architecture.html](../docs/architecture.html) — single-page b&w architecture artifact (v0).

## Roadmap
- [roadmap/14-session-plan.md](roadmap/14-session-plan.md) — full ladder, S3 → S24 (updated post-ADR-0011+0012), current session marker.
- [roadmap/differentiators.md](roadmap/differentiators.md) — D1–D6, what each one means and where it lives.

## Decisions (ADRs)
- [decisions/adr-0001-jtbd-and-scope.md](decisions/adr-0001-jtbd-and-scope.md) — JTBD, audience, success criteria, anti-scope (S4, accepted).
- [decisions/adr-0002-runtime-shape.md](decisions/adr-0002-runtime-shape.md) — turn loop, async generator, state-replaced (S5, accepted).
- [decisions/adr-0003-tool-surface.md](decisions/adr-0003-tool-surface.md) — Tool Protocol, double-gated permissions, native+browser+MCP unification (S5, accepted).
- [decisions/adr-0004-provider-layer.md](decisions/adr-0004-provider-layer.md) — canonical messages, ProviderAdapter, cost router v0 / D1 (S5, accepted).
- [decisions/adr-0005-session-state.md](decisions/adr-0005-session-state.md) — object store, refs, branches, replay / D3 (S5, accepted).
- [decisions/adr-0006-skills-runtime.md](decisions/adr-0006-skills-runtime.md) — disk SKILL.md, catalog digest + per-turn active block, keyword + explicit retrieval / D2 (S11, accepted).
- [decisions/adr-0007-live-html-notes-artifact.md](decisions/adr-0007-live-html-notes-artifact.md) — JSONL note store + server-side HTML render + per-turn hook + `notes_append` tool / D4 (S12, accepted).
- [decisions/adr-0008-browser-and-mcp.md](decisions/adr-0008-browser-and-mcp.md) — `web_fetch` v0 (browser-shaped slot) + MCP client with stdio + `.tern/mcp.json` / D5 + D6 (S13, accepted).
- [decisions/adr-0009-core-loop-tool-parity.md](decisions/adr-0009-core-loop-tool-parity.md) — `write_file`, `glob`, `grep`, `bash` behind the existing Tool Protocol; bash gets a three-line defense (S14, accepted).
- [decisions/adr-0010-secret-redaction-policy.md](decisions/adr-0010-secret-redaction-policy.md) — sink-level redactor with stable per-session placeholders; default-on / M13 (S14, accepted).
- [decisions/adr-0011-cognitive-routing-and-recall.md](decisions/adr-0011-cognitive-routing-and-recall.md) — per-turn router (decision tree → LLM fallback) + per-repo similarity recall (KNN over span embeddings) + curator with Bayesian priors over outcomes; sequenced S18–S19 (S16+, accepted).
- [decisions/adr-0012-long-running-build-hardening.md](decisions/adr-0012-long-running-build-hardening.md) — intra-turn summarizer + sub-turn delegate + background proc tool + read cache + diff preview + session cost budgets; sequenced S21 (S16+, accepted).

## Concepts
- [concepts/canonical-message-log.md](concepts/canonical-message-log.md) — the one lock: internal log ≠ provider wire format.
- [concepts/14-modules.md](concepts/14-modules.md) — M0–M14, what each module owns.
- [concepts/m11-observability.md](concepts/m11-observability.md) — events, span pairing, ndjson sink, replay (S6).
- [concepts/m4-canonical-messages.md](concepts/m4-canonical-messages.md) — frozen canonical types + first provider adapter, the lock installed (S7).
- [concepts/m1-m0-turn-loop.md](concepts/m1-m0-turn-loop.md) — turn loop, CLI entry, D1 routing skeleton (S8).
- [concepts/tool-protocol-and-permissions.md](concepts/tool-protocol-and-permissions.md) — Tool Protocol + double permission gate (S9).
- [concepts/tern-vs-hermes-scope.md](concepts/tern-vs-hermes-scope.md) — why S15→S20 extends the ladder; why the foundation already supports it; notes_append pseudo-XML pitfall.

## Entities
- [entities/tern.md](entities/tern.md) — the project itself.
- [entities/aider.md](entities/aider.md) — Python coding agent, our primary lift source.
- [entities/claude-code.md](entities/claude-code.md) — TS clone we cloned for design DNA.
- [entities/browser-use.md](entities/browser-use.md) — D5 browser tool library.
- [entities/mcp-python-sdk.md](entities/mcp-python-sdk.md) — D6 MCP client library.

## Sources
- [sources/wiki-llmops-synthesis.md](sources/wiki-llmops-synthesis.md) — agent fundamentals + retrieval + tools (8 wiki pages).
- [sources/wiki-security-reliability.md](sources/wiki-security-reliability.md) — threat modeling, redaction, release-it patterns.
- [sources/wiki-storage-decoupling.md](sources/wiki-storage-decoupling.md) — DDIA + clean-architecture for replay/branch.
- [sources/ref-claude-code.md](sources/ref-claude-code.md) — claude-code TS extraction.
- [sources/ref-aider.md](sources/ref-aider.md) — aider Python extraction.
- [sources/ref-browser-mcp.md](sources/ref-browser-mcp.md) — browser-use + MCP integration spec.

## Sessions
- [sessions/S1-grounding-decisions.md](sessions/S1-grounding-decisions.md) — name=tern, repo=A1, six diffs, HTML artifact contract.
- [sessions/S2-grounding-execution.md](sessions/S2-grounding-execution.md) — clones + wiki reads + synthesis + architecture.html.
- [sessions/S3-skeleton-green-floor.md](sessions/S3-skeleton-green-floor.md) — pyproject + Typer CLI + 3 smoke tests + first commit.
- [sessions/S4-phase-0-jtbd.md](sessions/S4-phase-0-jtbd.md) — ADR-0001 anchor (JTBD, scope, success criteria, anti-scope).
- [sessions/S5-phase-1-adrs.md](sessions/S5-phase-1-adrs.md) — ADRs 0002–0005, design locked end-to-end.
- [sessions/S6-m11-observability.md](sessions/S6-m11-observability.md) — events, spans, ndjson sink, `tern spans` CLI, 8 tests green.
- [sessions/S7-m4-canonical-messages.md](sessions/S7-m4-canonical-messages.md) — canonical message log + Bedrock-Anthropic adapter, 39/39 green.
- [sessions/S8-m1-m0-turn-loop.md](sessions/S8-m1-m0-turn-loop.md) — turn loop + CLI + D1 routing, live Bedrock end-to-end, 54/54 green.
- [sessions/S9-m5-tools-m2-chat-ui.md](sessions/S9-m5-tools-m2-chat-ui.md) — M5 tools (read_file, edit_block) + M2 Textual chat UI, double permission gate, 92/92 green.
- [sessions/S9.5-inline-repl-streaming.md](sessions/S9.5-inline-repl-streaming.md) — Ripped Textual; built inline REPL on prompt_toolkit + rich.live; day-1 Bedrock streaming; diff-up-front edit_block prompt. 96/96 green.
- [sessions/S10-session-graph.md](sessions/S10-session-graph.md) — D3 landed: content-addressed turn-object store + session refs + transcripts; `tern log/resume/branch/replay`; chat `--resume`. 108/108 green.
- [sessions/S11-skills-runtime.md](sessions/S11-skills-runtime.md) — D2 landed: disk SKILL.md catalog, per-turn keyword + explicit-mention retrieval, `tern skills` CLI, live Bedrock smoke green. 125/125 green.
- [sessions/S12-live-html-notes-artifact.md](sessions/S12-live-html-notes-artifact.md) — D4 landed: JSONL note store, server-side HTML render, `notes_append` tool, `tern notes` CLI, live Bedrock smoke green. 137/137 green.
- [sessions/S13-browser-and-mcp.md](sessions/S13-browser-and-mcp.md) — D5 + D6 landed: `WebFetchTool` v0 (urllib, text-only) + full MCP stdio bridge (`.tern/mcp.json`); live Bedrock smoke green; real-subprocess MCP integration test. 159/159 green.
- [sessions/S14-core-loop-parity-redaction-retry.md](sessions/S14-core-loop-parity-redaction-retry.md) — core-loop tool parity (write_file/glob/grep/bash) + sink-level secret redaction (ADR-0010) + Bedrock full-jitter retry/backoff (M12). 210/210 green, +51 tests, live Bedrock smoke green.
- [sessions/S15-persistent-memory.md](sessions/S15-persistent-memory.md) — memory store (MEMORY.md + USER.md), memory tool, skill_manage tool, notes_append fix. 246/246 green, +50 tests.
- [sessions/S16-multi-model-config-pricing.md](sessions/S16-multi-model-config-pricing.md) — BedrockNova + OpenAI adapters, pricing table, config/secrets split, `tern models`. 295/295 green, +35 tests.
- [sessions/S17-repo-scoped-memory.md](sessions/S17-repo-scoped-memory.md) — repo-scoped memory tier (Layer A): `repo_store.py`, `render_all_banners_with_repo`, `scope="repo"` on MemoryTool. 327/327 green, +31 tests.

---

## How to read this index
1. Looking for a fact about a library or project? → `entities/`
2. Looking for a pattern or primitive? → `concepts/`
3. Looking for "why did we pick X over Y"? → `decisions/`
4. Looking for what we read? → `sources/`
5. Looking for what happened when? → `log.md` or `sessions/`
6. Looking for what's next? → `roadmap/14-session-plan.md`
