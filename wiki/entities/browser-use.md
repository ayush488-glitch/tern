---
title: browser-use
type: entity
created: 2026-05-27
updated: 2026-05-27
sources: [../sources/ref-browser-mcp.md]
tags: [reference, browser, d5, m9]
---

# browser-use

Python library for headless-browser-as-agent-tool. Drives Chromium via CDP (no Playwright). Tern's D5 browser tool.

Repo (cloned, gitignored): `.scratch/grounding/refs/browser-use`.

## Public surface we use
`Agent, BrowserSession (= Browser), BrowserProfile, ChatBrowserUse / ChatOpenAI / ChatAnthropic / ChatGoogle / ChatOllama, AgentHistoryList, ActionResult`.

## Object ownership in Tern
- `BrowserSession` → ONE per Tern session. Long-lived, expensive to start.
- `BrowserProfile` → built once at startup from Tern config.
- `Agent` → constructed PER tool-call. Disposable. `agent.run(max_steps=N)`.
- LLM: pluggable via Tern's provider, default `ChatBrowserUse` only when `BROWSER_USE_API_KEY` set, else fall back to parent agent's Chat* class.

## The sub-agent contract
Browser-use Agent IS already a sub-agent loop. **Tern must NOT re-loop it.** Call `agent.run()` once with budgeted `max_steps`, consume `AgentHistoryList → ToolResult`:
```
text       = history.final_result()
ok         = history.is_successful()
error      = "; ".join(history.errors()) or None
artifacts  = history.screenshots() + attachments
meta       = {"steps": ..., "urls": ..., "actions": ..., "tokens": ...}
```

## Gotchas
- CDP-driven, not Playwright. Chromium install via `uvx browser-use install`.
- asyncio only. No sync API.
- Headless must be explicit in BrowserProfile.
- `success=True` requires `is_done=True` (Pydantic validator).

See [sources/ref-browser-mcp.md](../sources/ref-browser-mcp.md) Part A for the full integration spec.
