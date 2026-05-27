# Tern — wiki index

The catalog. Every wiki page is listed here with a one-line summary.
Update on every ingest, every filed query, every session end, every decision.

---

## Top-level
- [AGENTS.md](../AGENTS.md) — schema. How this wiki is structured and maintained.
- [log.md](log.md) — chronological ops log.
- [docs/architecture.html](../docs/architecture.html) — single-page b&w architecture artifact (v0).

## Roadmap
- [roadmap/14-session-plan.md](roadmap/14-session-plan.md) — full ladder, S3 → S16, current session marker.
- [roadmap/differentiators.md](roadmap/differentiators.md) — D1–D6, what each one means and where it lives.

## Decisions (ADRs)
*(none filed yet — first ADRs land in S5)*

## Concepts
- [concepts/canonical-message-log.md](concepts/canonical-message-log.md) — the one lock: internal log ≠ provider wire format.
- [concepts/14-modules.md](concepts/14-modules.md) — M0–M14, what each module owns.

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

---

## How to read this index
1. Looking for a fact about a library or project? → `entities/`
2. Looking for a pattern or primitive? → `concepts/`
3. Looking for "why did we pick X over Y"? → `decisions/`
4. Looking for what we read? → `sources/`
5. Looking for what happened when? → `log.md` or `sessions/`
6. Looking for what's next? → `roadmap/14-session-plan.md`
