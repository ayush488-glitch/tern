"""browser tools — S23 / D5 Playwright-backed browser for Tern.

Five tools sharing one persistent browser context per Python process:
  browser_navigate  — go to URL, return page title + URL
  browser_snapshot  — return accessibility tree text (page content)
  browser_click     — click element by CSS selector or text
  browser_type      — type text into an element
  browser_vision    — screenshot the current page → ImageBlock

Design principles (ADR-0008):
- One Playwright Chromium context per process (lazy init, atexit close).
- navigate/snapshot/vision = non-destructive (no gate prompt).
- click/type = destructive (approval prompt in default mode).
- On any Playwright error: return ToolResult(ok=False, error=...).
- No Playwright import at module import time — guard with try/except at
  use time so tests can import the module without playwright installed.
- 30s navigation timeout; 10s for click/type/snapshot.
"""
from __future__ import annotations

import asyncio
import atexit
import base64
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tern.core.canonical import ImageBlock
from tern.tools.protocol import ToolAnnotations, ToolContext, ToolResult

# ---------------------------------------------------------------------------
# Singleton browser session
# ---------------------------------------------------------------------------

_session: _BrowserSession | None = None


def _get_session() -> _BrowserSession:
    global _session
    if _session is None:
        _session = _BrowserSession()
    return _session


class _BrowserSession:
    """Lazy Playwright Chromium context. One per process."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()
        atexit.register(self._sync_close)

    async def _ensure(self) -> Any:
        """Return the current page, launching browser if needed."""
        async with self._lock:
            if self._page is None:
                try:
                    from playwright.async_api import async_playwright
                except ImportError as e:
                    raise RuntimeError(
                        "playwright not installed — run: pip install playwright && "
                        "python -m playwright install chromium"
                    ) from e
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                ctx = await self._browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    ),
                )
                self._page = await ctx.new_page()
        return self._page

    async def navigate(self, url: str) -> dict[str, str]:
        page = await self._ensure()
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        return {"url": page.url, "title": await page.title()}

    async def snapshot(self) -> str:
        """Return page accessibility tree as text."""
        page = await self._ensure()
        snap = await page.accessibility.snapshot(interesting_only=True)
        return _acc_to_text(snap)

    async def click(self, selector: str) -> None:
        page = await self._ensure()
        await page.click(selector, timeout=10_000)

    async def type_text(self, selector: str, text: str, clear: bool) -> None:
        page = await self._ensure()
        if clear:
            await page.fill(selector, "", timeout=10_000)
        await page.type(selector, text, timeout=10_000)

    async def screenshot_png(self) -> bytes:
        page = await self._ensure()
        png: bytes = await page.screenshot(type="png", full_page=False)
        return png

    def _sync_close(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                _t = asyncio.ensure_future(self._close())
                del _t
            else:
                loop.run_until_complete(self._close())
        except Exception:
            pass

    async def _close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# ---------------------------------------------------------------------------
# Accessibility tree → text
# ---------------------------------------------------------------------------


def _acc_to_text(node: Any, depth: int = 0) -> str:
    if node is None:
        return ""
    indent = "  " * depth
    role = node.get("role", "")
    name = node.get("name", "")
    value = node.get("value", "")

    line = indent
    if role:
        line += f"[{role}]"
    if name:
        line += f" {name!r}"
    if value:
        line += f" = {value!r}"

    parts = [line.rstrip()]
    for child in node.get("children") or []:
        parts.append(_acc_to_text(child, depth + 1))
    return "\n".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# browser_navigate
# ---------------------------------------------------------------------------


class BrowserNavigateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., description="Absolute http(s) URL to navigate to.")


class BrowserNavigateTool:
    """Navigate the browser to a URL. Returns page title and final URL."""

    name = "browser_navigate"
    title = "Browser Navigate"
    description = (
        "Navigate the browser to an http(s) URL. Loads the page and "
        "returns the page title and final URL (after redirects). Use "
        "browser_snapshot to read content, browser_click/type to interact."
    )
    args_model: type[BaseModel] = BrowserNavigateArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, BrowserNavigateArgs)
        try:
            info = await _get_session().navigate(args.url)
        except Exception as exc:
            return ToolResult(ok=False, content=f"navigate failed: {exc}", error=str(exc))
        return ToolResult(
            ok=True,
            content=f"Navigated to: {info['url']}\nTitle: {info['title']}",
            metadata=info,
        )


# ---------------------------------------------------------------------------
# browser_snapshot
# ---------------------------------------------------------------------------


class BrowserSnapshotArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserSnapshotTool:
    """Return the accessibility tree of the current browser page as text."""

    name = "browser_snapshot"
    title = "Browser Snapshot"
    description = (
        "Return the accessibility tree of the current browser page as text. "
        "Shows interactive elements (buttons, links, inputs) and their labels. "
        "Use after browser_navigate to read page content."
    )
    args_model: type[BaseModel] = BrowserSnapshotArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        try:
            text = await _get_session().snapshot()
        except Exception as exc:
            return ToolResult(ok=False, content=f"snapshot failed: {exc}", error=str(exc))
        if not text.strip():
            text = "(page returned empty accessibility tree)"
        if len(text) > 12_000:
            text = text[:12_000] + "\n…[truncated]"
        return ToolResult(ok=True, content=text)


# ---------------------------------------------------------------------------
# browser_click
# ---------------------------------------------------------------------------


class BrowserClickArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str = Field(
        ...,
        description=(
            "CSS selector or Playwright text selector (e.g. 'button#submit', "
            "'text=Sign in', '[aria-label=\"Search\"]')."
        ),
    )


class BrowserClickTool:
    """Click an element in the current browser page."""

    name = "browser_click"
    title = "Browser Click"
    description = (
        "Click an element on the current browser page identified by a CSS "
        "selector or Playwright text selector. Destructive: triggers a "
        "permission prompt in default mode."
    )
    args_model: type[BaseModel] = BrowserClickArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, BrowserClickArgs)
        try:
            await _get_session().click(args.selector)
        except Exception as exc:
            return ToolResult(ok=False, content=f"click failed: {exc}", error=str(exc))
        return ToolResult(ok=True, content=f"Clicked: {args.selector}")


# ---------------------------------------------------------------------------
# browser_type
# ---------------------------------------------------------------------------


class BrowserTypeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str = Field(..., description="CSS or text selector for the input element.")
    text: str = Field(..., description="Text to type.")
    clear: bool = Field(default=True, description="Clear the field before typing.")


class BrowserTypeTool:
    """Type text into an input element in the current browser page."""

    name = "browser_type"
    title = "Browser Type"
    description = (
        "Type text into an input field on the current browser page. "
        "Destructive: triggers a permission prompt in default mode."
    )
    args_model: type[BaseModel] = BrowserTypeArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, BrowserTypeArgs)
        try:
            await _get_session().type_text(args.selector, args.text, args.clear)
        except Exception as exc:
            return ToolResult(ok=False, content=f"type failed: {exc}", error=str(exc))
        return ToolResult(
            ok=True,
            content=f"Typed {len(args.text)} chars into: {args.selector}",
        )


# ---------------------------------------------------------------------------
# browser_vision
# ---------------------------------------------------------------------------


class BrowserVisionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserVisionTool:
    """Screenshot the current browser page and return it as an ImageBlock."""

    name = "browser_vision"
    title = "Browser Vision"
    description = (
        "Take a screenshot of the current browser page and return it as an "
        "image. The image is injected into the next model turn so you can "
        "describe or analyse the page visually."
    )
    args_model: type[BaseModel] = BrowserVisionArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=False, read_only=True, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        try:
            png = await _get_session().screenshot_png()
        except Exception as exc:
            return ToolResult(ok=False, content=f"vision failed: {exc}", error=str(exc))
        b64 = base64.b64encode(png).decode()
        size_kb = len(png) // 1024
        return ToolResult(
            ok=True,
            content=f"Browser screenshot: {size_kb} KB PNG",
            image_blocks=(ImageBlock(media_type="image/png", data_b64=b64),),
        )


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

from tern.tools.protocol import Tool  # noqa: E402

_: Tool
_ = BrowserNavigateTool()
_ = BrowserSnapshotTool()
_ = BrowserClickTool()
_ = BrowserTypeTool()
_ = BrowserVisionTool()

__all__ = [
    "BrowserClickArgs",
    "BrowserClickTool",
    "BrowserNavigateArgs",
    "BrowserNavigateTool",
    "BrowserSnapshotArgs",
    "BrowserSnapshotTool",
    "BrowserTypeArgs",
    "BrowserTypeTool",
    "BrowserVisionArgs",
    "BrowserVisionTool",
]
