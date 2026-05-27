---
title: "ADR-0001 — JTBD and scope"
type: decision
created: 2026-05-27
updated: 2026-05-27
status: accepted
supersedes: []
superseded_by: []
tags: [tern, scope, jtbd, phase-0]
---

# ADR-0001 — Job-to-be-done and scope

## Status
Accepted, 2026-05-27.

## Context

Before any code beyond the skeleton, Tern needs an ADR that answers four questions sharply:

1. Who is this for, on day one?
2. What job do they hire it to do?
3. What is it explicitly NOT?
4. What does "shipped" look like at week 1, 2, 4?

Without these locked in writing, every future architectural choice (model selection, tool surface, sandboxing strictness, distribution channel, billing posture) drifts. The 14-session plan and the six differentiators (D1–D6) only make sense relative to a specific JTBD; choose a different JTBD and the priority order collapses.

This ADR is the anchor. Future ADRs (0002 runtime shape, 0003 tool surface, 0004 provider layer, 0005 session/state) all cite back to it.

## Decision

### Primary user — open-source contributors, day 1
Tern's audience is **open-source contributors and engineers comfortable in a terminal**, from the first public README. Not an internal tool that gets open-sourced later. Not a closed beta. The repo is public from commit one of the open-source push, the README is written for a stranger, and `pipx install tern` is the supported install path.

This means contribution surface is a first-class concern: clear `AGENTS.md`, the wiki as the design source of truth, ADRs for every non-obvious choice, tests as documentation, no proprietary blob anywhere.

### Primary job — investigate + edit + browse, all in the terminal
Tern is hired to do the full coding-agent surface in a terminal, with a beautified TUI:

- **Investigate** — read code, grep, follow symbols, run tests, summarize, ask clarifying questions, build a working theory. Reflection retry loop closes the gap when the first answer is wrong.
- **Edit** — search/replace edit blocks (lifted from aider), atomic file writes, git commits per turn.
- **Browse** — browser-use as a real tool (D5). Open pages, scrape, dogfood, summarize. Same Tool Protocol, same permission gate as native tools.
- **Call MCP servers** — MCP client built-in (D6). Remote tools register into the same tool registry under `<server>.<tool>` namespace, with the same approval gate.

The interface is the terminal. There is no Electron, no web UI, no desktop app. The TUI is **textual** (Python-native reactive widgets) — beautiful but terminal-only. `--print` mode for non-interactive / piped / CI use.

### What it isn't (anti-scope)
- ❌ Not an autonomous overnight agent. Tern runs synchronous turns with a max_steps cap and surfaces approval prompts on writes. We do not aim for "kick off and walk away."
- ❌ Not a hosted SaaS. There is no `tern.dev` cloud product. Provider keys live on the user's machine. The runtime is the user's machine.
- ❌ Not a chatbot. The output isn't conversation; it's edits, commits, browser actions, MCP calls, and structured artifacts.
- ❌ Not an IDE plugin. No VS Code extension, no JetBrains integration, no Vim plugin in v1. Terminal-native or not at all.
- ❌ Not a free-tier-or-bust product. There's **no cost ceiling per session**. Tern's D1 cost router optimizes choice (Haiku where Haiku suffices), but we don't artificially gate premium models — the user owns their bill.
- ❌ Not a "small model can't drive it" agent. Tern is designed around frontier-class reasoning at the planner tier; downgrading to small models is a routing decision, not the default posture.
- ❌ Not a vendor-locked artifact. M4's canonical message log makes provider-swap a per-turn decision, not a refactor.

### Cost posture — quality first, routing second
No hard `$ per session` cap. The default policy uses frontier-class models (Sonnet / Opus on Bedrock) and the cost router (D1) substitutes cheaper models only when the turn's work is provably cheap-suitable (lint, format, scaffold, autocomplete). Observability (M11) reports cost-per-turn so the user sees the bill in real time and decides; Tern doesn't decide for them.

This is a deliberate inversion of the "cheap-by-default, premium-on-flag" posture. Open-source contributors who self-host their keys want quality first; routing is the optimization, not the constraint.

## Success criteria — week 1 / 2 / 4

### Week 1 — design-locked, skeleton green
- [x] Repo public-ready skeleton (S3 done, gates green).
- [ ] All 5 ADRs filed (S5 ships ADR-0002..0005).
- [ ] `architecture.html` + `wiki/index.md` + `AGENTS.md` linkable from README.
- Demo-visible: `pipx install -e .` works, `tern --version` runs, `pytest` green on a clean machine.

### Week 2 — minimal viable agent
- [ ] M11 observability skeleton (S6).
- [ ] M4 canonical messages + Bedrock-Anthropic adapter (S7).
- [ ] M1 + M0 turn loop + CLI: `tern run "say hello"` → real Bedrock call → printed reply (S8).
- Demo-visible: a one-shot turn against Bedrock, with span output proving observability.

### Week 4 — interactive coding agent
- [ ] M5 + M2 slice: `read_file` + `edit_block` tools, textual TUI, slash commands, permission prompt (S9).
- Demo-visible: `tern` opens an interactive session, the user asks "fix the typo in src/foo.py", Tern reads, proposes edit, prompts for approval, applies, commits. End-to-end. **First "this is real" moment.**

After week 4, Stage III (D1–D6 differentiators) and Stage IV (hardening + ship) follow per [14-session-plan](../roadmap/14-session-plan.md).

## Alternatives rejected

### A. "Build for me first, open-source later"
Internal-tool-then-open-source has a known failure mode: the README, the contributor docs, and the test suite all lag because they aren't load-bearing for the original user. By the time you decide to open-source, retrofitting them is a multi-week project that competes with shipping. Public from day 1 makes "AGENTS.md is current, ADRs are filed, tests document behavior" a working constraint, not a polish pass.

### B. "Edit-only first, browse + MCP later"
Splitting the surface (start aider-clone, add browser/MCP later) would simplify Phase II but break the architectural lock. M5's Tool Protocol must accommodate browser-use's sub-agent shape and MCP's ClientSessionGroup from day 1, or we end up with two competing tool abstractions and a refactor. Designing with all three in mind keeps M5 honest. Implementation can be staged (S9 ships native tools, S13 adds browser + MCP), but the design must not.

### C. "GUI / web UI for accessibility"
A web UI broadens audience but breaks the trust model: the runtime is on the user's machine, the keys are the user's, and that's a feature, not an inconvenience. A web UI implies a service we'd run, which implies billing, auth, secrets handling, and a TOS — none of which are in scope. Terminal-native sidesteps the entire category.

### D. "Hard $ cap per session, default free-tier model"
Cost-capping by default forces D1's policy to start in degraded mode. Most coding-agent failures (wrong edit, missed dependency, broken test) come from too-small a planner model, not too-big. Defaulting to quality and letting D1 substitute downward is the right asymmetry: the cost of a bad edit is hours; the cost of a Sonnet turn is cents.

### E. "Autonomous overnight runs"
Strikes the sweet spot of being both very hard and not what users want. Autonomy at this level requires sandboxing maturity (containerized exec, snapshot/rollback, network policy) Tern won't have for a while. Synchronous-with-approval is honest about the current state of the art.

## Consequences

### Positive
- **Public-from-day-1 forces discipline.** Wiki, AGENTS.md, ADRs aren't aspirational; they're the contract with contributors.
- **Quality-first cost posture matches the open-source contributor mindset.** They self-host their keys; they want the agent to actually work.
- **Full surface from day 1 (in design)** means M5 is right the first time. Browser and MCP plug in at S13 without a refactor because their shape was accounted for in S5's ADR-0003.
- **Terminal-native simplifies the trust model.** No cloud, no auth, no secrets escrow.

### Negative / accepted costs
- **README and docs work is non-deferrable.** Every session must keep wiki + README current. We accept the maintenance tax.
- **Audience is narrower than "everyone with a coding question."** Engineers in terminals only. Acceptable; matches the team and the project ethos.
- **No revenue model in v1.** This is an open-source foundation; monetization is a future Antern decision, not a Tern decision.
- **Bedrock-first is a temporary tilt.** OpenAI / Anthropic-direct / OpenRouter adapters land later under the same M4 Protocol; users on those stacks wait.

### Open questions deferred
- **Telemetry / opt-in usage analytics.** Decide before public push. Default off; opt-in only.
- **`tern doctor` self-diagnostic command.** Probably part of M14 polish (S15).
- **Plugin marketplace shape.** Skills + MCP cover the extension surface for now; a registry is post-v1.

## References
- [14-session-plan](../roadmap/14-session-plan.md) — milestones this ADR anchors.
- [differentiators](../roadmap/differentiators.md) — D1–D6 the JTBD requires.
- [canonical-message-log](../concepts/canonical-message-log.md) — the lock that makes "all providers, no cost ceiling" tractable.
- [14-modules](../concepts/14-modules.md) — M0–M14 the surface decomposes into.
- [architecture.html](../../docs/architecture.html) — the visual all of the above resolves to.
