---
title: S23 — Real Search + Browser Tools
type: session
created: 2026-05-29
updated: 2026-05-29
sources: [roadmap/14-session-plan.md]
tags: [tern, s23, browser, playwright, web-search, tavily, duckduckgo]
---

# S23 — Real Search + Browser Tools

## What was built

### web_search tool (tools/native/web_search.py)
Primary backend: Tavily (one POST, structured JSON, markdown results).
Fallback: DuckDuckGo HTML lite scrape via stdlib `urllib` (no API key needed).
Key lives at `search.tavily_api_key` in `~/.tern/config.json` (now a valid key).
Args: `query` (required), `max_results` (1-10, default 5).
Result: `## N. Title\n<url>\n<snippet>` blocks, 8000 char cap.
`open_world=True, destructive=False` — no gate prompt.

### browser tools (tools/native/browser.py) — 5 tools, 1 session
One `_BrowserSession` singleton per process (lazy Playwright Chromium launch).
Headless, 1280x800, Chrome UA. atexit close.

| Tool | destructive | action |
|------|-------------|--------|
| `browser_navigate` | False | `page.goto()`, returns title + final URL |
| `browser_snapshot` | False | `page.accessibility.snapshot()` → text tree, 12K cap |
| `browser_click` | True | `page.click(selector)`, 10s timeout |
| `browser_type` | True | `page.fill()` clear + `page.type()`, 10s timeout |
| `browser_vision` | False | `page.screenshot(png)` → ImageBlock (uses S22 image injection) |

All registered in `cli.py`. All exported from `tools/native/__init__.py`.

Playwright import is guarded (`try: from playwright.async_api import...`) so
importing the module never fails even if playwright isn't installed — the error
surfaces only on actual `_ensure()` call.

### config.py
Added `search.tavily_api_key` to `_VALID_KEYS`.

## Numbers

| Metric | Value |
|--------|-------|
| ruff | 0 errors (74 files) |
| mypy --strict | 0 errors (74 files) |
| pytest | 490/490 passed, 1 skipped |
| new tests | +26 (test_s23_search_browser.py) |
| new files | 3 (web_search.py, browser.py, test_s23_search_browser.py) |
| modified | 3 (native/__init__.py, cli.py, config.py) |

## Key decisions

1. **Singleton browser session** per process (not per turn). Playwright startup
   is ~300ms; one session avoids paying that on every call. The model can
   navigate + snapshot + click in sequence without re-launching.

2. **click/type = destructive**. They mutate page state (submit forms, fill
   passwords). The ADR-0003 gate prompts in default mode; `--yes` suppresses.

3. **Accessibility tree, not HTML**. `page.accessibility.snapshot()` returns
   the semantic tree — labels, roles, values. Much cheaper tokens than raw HTML.
   Raw HTML available via `web_fetch` if needed.

4. **DuckDuckGo fallback** uses HTML-lite (non-JS), not the API. Requires no key
   and is reliable for basic queries. Snippet extraction is brittle but good
   enough for fallback — Tavily is the production path.

5. **browser_vision reuses S22 image injection**. `BrowserVisionTool` returns
   `image_blocks=(ImageBlock(...),)` in `ToolResult`, exactly like
   `ScreenshotTool`. The loop's existing `pending_images` path delivers it.

## What's next

S24: M14 polish + pipx install + walkthrough chapters.
