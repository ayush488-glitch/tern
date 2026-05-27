# Tern — ops log

Append-only. Newest at the bottom. Every entry starts with `## [YYYY-MM-DD]`.

Types: `ingest | query | lint | session-end | decision | milestone | rename`.

---

## [2026-05-27] milestone | grounding complete
Cloned 5 reference repos. 3 wiki-deep-read syntheses + 3 reference-repo extractions. 6 differentiators locked. 14 modules named. One-page b&w architecture artifact at docs/architecture.html.

## [2026-05-27] decision | name = tern
Originally proposed `antern`, user picked `tern`. Shorter, ergonomic CLI binary, still ties to Antern brand without being a literal substring.

## [2026-05-27] rename | antern → tern
Applied across .scratch/grounding/notes/* and docs/architecture.html. No residue.

## [2026-05-27] decision | ADRs 0002–0005 (S5 done) — design locked end-to-end
ADR-0002 runtime-shape: turn = async generator yielding TurnEvents; TurnState frozen + state-replaced; multi-source termination (done | max_steps | abort | denial | provider error); reflection retry as event with cap=3; sub-agent contract sits at M5.
ADR-0003 tool-surface: one Tool Protocol, three siblings (NativeTool, BrowserTool, MCPTool); Pydantic schemas; double-gated permissions (registry filter + call-site enforce); MCP annotations as canonical vocabulary; modes safe/default/yolo; no Docker sandbox v1.
ADR-0004 provider-layer: CanonicalMessage / ContentBlock / ToolSpec frozen+hashable; ProviderAdapter Protocol with pure to_wire/from_wire; v0 = bedrock_anthropic.py; D1 v0 = FrontierFirstPolicy (rule-based, frontier default, downgrade only when provably cheap); litellm = ONE backend not THE abstraction.
ADR-0005 session-state: ~/.tern/projects/<cwd>/{objects, refs, sessions/*.jsonl, index.sqlite}; turn-object = {parent, role, content, model_id, cost, ts, seed}; sha256 content-address; branch = new ref; replay = walk parents re-feed canonical (pure | live | cross-model); workspace branching is git's job not Tern's.

## [2026-05-27] decision | ADR-0001 jtbd-and-scope (S4 done)
Open-source contributors day 1. Full surface: investigate + edit + browse + MCP. Terminal-native beautiful TUI (textual). NO cost ceiling — quality first, D1 routing optimizes downward only when provably cheap-suitable. Anti-scope: not autonomous, not SaaS, not chatbot, not IDE plugin, not free-tier-or-bust, not vendor-locked. Week 1/2/4 visibility milestones locked.

## [2026-05-27] milestone | S3 — repo skeleton, first green commit
pyproject.toml + src/tern/{__init__,cli}.py + tests/test_smoke.py. Four gates green: `tern --version`, `pytest` (3/3), `ruff check`, `mypy --strict`. Commit 38878b6 landed on a clean tree (28 tracked files; `.scratch/` correctly excluded). Stack: typer + rich; py3.10 floor for breadth.

## [2026-05-27] milestone | LLM Wiki bootstrapped
AGENTS.md schema, wiki/index.md, wiki/log.md, wiki/roadmap/14-session-plan.md, wiki/concepts/, wiki/entities/, wiki/sources/, wiki/sessions/ scaffolded. Pattern: ingest / query / lint / session-handoff. This wiki is now THE persistent memory across sessions.
