---
title: S16 — Multi-model adapters, config/secrets, pricing
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [s16, adapters, nova, openai, pricing, config, secrets]
---

# S16 — Multi-model adapters, config + secrets, pricing fold-in

## What shipped

- `src/tern/adapters/bedrock_nova.py` (268 lines) — Nova Lite / Pro / Micro via Bedrock InvokeModel. Native messages shape (`{role, content:[{text:...}]}`), `toolConfig.tools[].toolSpec`, tool-result blocks ride under user-role messages.
- `src/tern/adapters/openai_adapter.py` (10k bytes) — OpenAI Chat Completions via httpx (boto3 transitive — no new dep). OpenAI-style tool wrapper `{"type":"function","function":{...}}`. Key resolution: env → `~/.tern/secrets.json` → TTY prompt.
- `src/tern/core/pricing.py` — `Pricing` dataclass + `_PRICING` table for Anthropic / Nova / GPT families. `pricing_for(model_id)` and `cost_for(model_id, in, out)`.
- `src/tern/core/secrets.py` — `~/.tern/secrets.json` chmod 600, atomic writes. `*_KEY|_TOKEN|_SECRET` lands here.
- `src/tern/core/config.py` — `~/.tern/config.json` for non-secrets (`default_model`). `_VALID_KEYS` guard.
- `src/tern/core/routing.py` (rewritten) — `adapter_for_model(model_id)` factory, dispatches by prefix:
  - `anthropic.claude*` → BedrockAnthropic
  - `amazon.nova*` → BedrockNova
  - `gpt-*` → OpenAI
  Adding a family = one new branch + one new file (ADR-0004 honored).
- `src/tern/cli.py` — `tern run --model/-m`, `tern config set/get/show`, `tern models`. Model precedence: `--model` > config `default_model` > purpose default.

## Pitfall caught + fixed

**Anthropic stream() wasn't folding pricing in.** Nova and OpenAI use `complete()`, which I'd already wired to `cost_for`. But the loop calls `stream()` for Anthropic on Bedrock, and that path was hardcoding `usd_in=usd_out=0.0`. Result: Sonnet always banner'd `$0.0000` while Nova showed real cost. Fix: import `cost_for` inside `stream()` and fold same as `complete()`. Live smoke now shows `cost $0.0099` for Sonnet, `cost $0.0002` for Nova.

Lesson: pricing fold-in must happen in **every code path that builds a Cost**. Adapter audit checklist now has a "grep `usd_in=0.0` after writing any adapter" step.

## Gates

- pytest **295/295** (was 260 at S15; +35: 11 secrets/config + 6 pricing + 5 routing-factory + 13 adapters)
- ruff ✅
- mypy --strict ✅ (52 source files; was 47)
- live Bedrock smoke: Sonnet `$0.0099`, Nova-lite `$0.0002`

## Decisions worth keeping

- **Secrets vs config split** — separate files, different perms. Tests can redirect both with one `TERN_HOME`.
- **Adapter dispatch by `model_id` prefix** — no registry. New family = one branch.
- **httpx, not openai SDK** — boto3 already pulls httpx in transitively; avoids a new top-level dep.

## Deferred

- Kimi K2.5 on Bedrock — needs OpenAI-style tool wrapper. Schedule when per-model serializer hook lands.

## Next session

S17 — repo-scoped operational memory tier (Layer A of the moat plan).
`<repo>/.tern/memory/{ARCH,DECISIONS,FAILURES,REVIEWERS}.md`, same store shape as S15 global memory, banners injected when the loop is running inside a repo. Then Layer B observers (git/PR), then `tern curate`. Vision/browser pushed to S20+. StackOverflow lookup on errors lands in the loop after Layer A.
