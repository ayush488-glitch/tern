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

## [2026-05-27] session-end | S6 m11-observability
Built M11 in one session. Eight source files (`core/events.py` + `obs/{paths,span,sink,recorder,render,replay}.py`) + `tests/test_obs.py` (5 tests). CLI gained `tern spans <session>`. Four gates green: pytest 8/8, ruff clean, mypy strict clean (11 files), `tern --version` 0.0.1. Decisions: span pair-matching uses `call_id` else opener-kind; singleton events become same-message closed-spans; `TERN_HOME` env override; ndjson sink fsyncs per write. Deferred: cost aggregation (S10), streaming events (S15), rebuild-on-corruption (S10). Touched: 4 wiki pages (concepts/m11-observability.md NEW, sessions/S6-m11-observability.md NEW, index.md, roadmap/14-session-plan.md). Next: S7 M4 canonical messages + Bedrock-Anthropic adapter.

## [2026-05-27] session-end | S7 M4 canonical messages + Bedrock-Anthropic adapter
TDD two cycles (canonical, adapter). 39/39 pytest, ruff clean, mypy --strict clean.
New: src/tern/core/canonical.py, src/tern/core/provider.py, src/tern/adapters/{__init__,bedrock_anthropic}.py.
Tests: tests/test_canonical.py (16), tests/test_bedrock_adapter.py (15).
Deps: +boto3>=1.34, dev +boto3-stubs[bedrock-runtime]>=1.34.
Wiki: +concepts/m4-canonical-messages.md, +sessions/S7-m4-canonical-messages.md, index+roadmap updated. Touched: 6 wiki files.

## [2026-05-27] session-end | S8 M1 + M0 turn loop + CLI
Built `tern run` end-to-end: turn loop (`core/loop.py`), Turn dataclass + TurnPurpose enum (`core/turn.py`), D1 routing skeleton (`core/routing.py`, static map, lru_cache adapter), CLI `run` command gated on TERN_LIVE=1, FakeAdapter test double. 15 new tests (4 routing + 11 loop) all green. Live smoke `TERN_LIVE=1 tern run "say hello in exactly three words"` → "Hello there friend." cost ~$0. Span tree renders cleanly. Pitfall logged: Claude 4 on Bedrock requires `us.` inference profile prefix (on-demand throughput unsupported). Gates: 54/54 pytest, ruff clean, mypy --strict clean (18 src files), `tern 0.0.1`.

## [2026-05-27] session-end | S9 M5 tools + M2 chat UI
Built the agent. Four commits: (1) Tool Protocol + Registry (gate 1, mode filter) + PermissionGate (gate 2, prompter) + 13 tests; (2) read_file + edit_block native tools w/ aider-style perfect_or_whitespace match + 15 tests; (3) multi-step loop with tool dispatch, ValidationError reflection retry, ApprovalRequested/Granted/Denied event pair, max_steps cap + 10 new loop tests; (4) Textual ChatApp with PermissionModal y/n overlay + `tern chat --mode {default,safe,yolo}` CLI. Bedrock-Anthropic adapter already handled tool_use/tool_result blocks from S7 — no changes needed. Gates: 92/92 pytest, ruff clean, mypy --strict clean (27 src files, textual.* override), live `tern run` smoke green. Pitfalls logged: Pydantic invariance on `args_model: type[BaseModel]`, Textual classes need `# type: ignore[misc]` under strict, BINDINGS needs ClassVar annotation for ruff RUF012. Demo surface: `TERN_LIVE=1 tern chat`. Next session S10 = M3 sessions + replay so the chat actually persists.

## [2026-05-27] session-end | S9.5 inline-repl-streaming
Ripped Textual TUI. Built inline REPL on prompt_toolkit + rich.live with day-1
Bedrock streaming and diff-up-front edit_block approval. LLMTextDelta event,
StreamingProviderAdapter Protocol, FakeStreamingAdapter test double, +4 tests.
Gates: pytest 96/96, ruff clean, mypy --strict clean (27 src), live Bedrock
streaming smoke green. Touched: 12 files.
## [2026-05-28] session-end | S10 session graph (D3) — store + log/resume/branch/replay, 108/108 green

## [2026-05-28] session-end | S11 skills runtime (D2) — disk-discovered SKILL.md, catalog digest + per-turn active block, 125/125 green
## [2026-05-28] decision | ADR-0006 skills runtime: project shadows user, keyword + explicit retrieval, cap 3 active

## [2026-05-28] decision | ADR-0007 live HTML notes artifact (D4)
## [2026-05-28] session-end | S12 live HTML notes artifact (D4) — 137/137 green, mypy strict ✅

## [2026-05-28] decision | ADR-0008 browser-shaped tool slot + MCP client (D5 + D6)
## [2026-05-28] session-end | S13 browser + MCP — WebFetchTool v0 (urllib, text-only) + full MCP stdio bridge with .tern/mcp.json config; 159/159 green, ruff clean, mypy --strict ✅; live Bedrock end-to-end demo `tern run "fetch http://example.com..."` succeeded with real tool call.

## [2026-05-28] decision | ADR-0009 core-loop tool surface parity (S14)
Four new tools land behind the existing protocol/registry/gate: write_file, glob, grep, bash. Bash gets three-line defense (registry filter in safe mode + 8-pattern deny-list + permission gate per call), 200 KiB output cap, 60s default timeout. Grep prefers ripgrep, falls back to Python re with identical output shape.

## [2026-05-28] decision | ADR-0010 secret redaction policy (S14, M13)
Redaction lives at the sink (NDJSONSpanSink), not at every tool. Stable per-session placeholders (`<KIND_N>`) so debug correlation works without leaking the secret. Pattern catalogue: AWS access key, GitHub/OpenAI tokens, Bearer, kv password, PEM private-key blocks, high-entropy fallback. Always-on with `redact=False` test escape hatch.

## [2026-05-28] session-end | S14 core-loop parity + redaction + Bedrock retry — 4 new tools (write_file/glob/grep/bash), obs/redact module wired into sink, full-jitter exponential retry on Bedrock throttle/5xx/timeout (4 retries, 0.5s base, 8s cap) wraps both invoke_model + invoke_model_with_response_stream. 210/210 green (+51 new tests), ruff clean, mypy --strict ✅, live Bedrock smoke ✅. Pitfalls logged: (a) `stdout.read(N)` doesn't block until N — needed chunked-loop reader; (b) `asyncio.TimeoutError` ≠ `TimeoutError` on py3.10; (c) bash regex group close.

## [2026-05-28] decision | roadmap extended S15→S20 — Hermes-shaped breadth ladder
Original S15 (M14 polish) and S16 (walkthrough) collapse into S20. New S15–S19 add: persistent memory (Hermes-shaped MEMORY.md + USER.md split, loaded once per session), skill_manage tool (CRUD on ~/.tern/skills), notes_append fix, model breadth (openai + nova + kimi + xai adapters + populated D1 cost router), vision (ImageBlock wiring + screenshot tool), real search (Tavily) + Playwright web_fetch swap + browser_navigate/click/type/snapshot, self-curation (`tern curate`). ~10 hours of focused work; foundation already supports it (ADR-0003/0004/0006). Source: wiki/concepts/tern-vs-hermes-scope.md. Reorder, don't remove.

## [2026-05-28] query | notes_append broken? | filed: concepts/tern-vs-hermes-scope.md
Symptom: HTML transcript present, "notes" section empty. Root cause: model emits literal `<notes_append>...</notes_append>` text as llm_text_delta events instead of a structured tool_use block; loop never sees a ToolCallBlock so the JSONL row never gets appended. Fix slated for S15: tighten tool description + add canonical-layer fallback parser that lifts the pseudo-XML into a synthetic ToolCallBlock. JSONL stays single source of truth for notes_render.
## [2026-05-28] session-end | S15 memory · skills self-management · notes_append fix · self-curation v0
## [2026-05-28] session-end | S16 multi-model + config + pricing
## [2026-05-28] fix | bedrock_anthropic _tool_result_to_wire empty content + test_skills memory bleed
## [2026-05-28] decision | ADR-0011 cognitive routing + KNN recall + Bayesian priors; S18-S19 sequenced
## [2026-05-28] decision | ADR-0012 long-running build hardening; S21 inserted, vision/browser/walkthrough push to S22-S24
## [2026-05-28] session-end | S17 repo-scoped memory tier (Layer A)
## [2026-05-29] session-end | S18 cognitive router + KNN recall (ADR-0011 subsystems 1+2)
