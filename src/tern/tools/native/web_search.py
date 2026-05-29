"""web_search — S23 tool.

Primary: Tavily search API (one call, markdown-formatted results).
Fallback: DuckDuckGo HTML lite scrape (no API key needed, no JS).

Key read from ~/.tern/config.json key "search.tavily_api_key".
If missing, falls back to DuckDuckGo silently.

Result shape (both backends):
    ## 1. <title>
    <url>
    <snippet>
    ...

Caps: max 10 results, total output 8000 chars.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tern.tools.protocol import ToolAnnotations, ToolContext, ToolResult

_MAX_RESULTS = 10
_MAX_OUTPUT_CHARS = 8_000
_USER_AGENT = "tern/0.0.1 (+https://github.com/antern-dev/tern)"


# ---------------------------------------------------------------------------
# args
# ---------------------------------------------------------------------------


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Search query.")
    max_results: int = Field(
        default=5,
        ge=1,
        le=_MAX_RESULTS,
        description="Maximum results to return (1-10).",
    )

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Tavily backend
# ---------------------------------------------------------------------------


async def _tavily_search(query: str, max_results: int, api_key: str) -> list[dict[str, str]]:
    """POST to Tavily /search and return a list of {title, url, content}."""
    import asyncio

    def _sync() -> list[dict[str, str]]:
        payload = json.dumps(
            {
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                }
            )
        return results

    return await asyncio.to_thread(_sync)


# ---------------------------------------------------------------------------
# DuckDuckGo HTML fallback
# ---------------------------------------------------------------------------


class _DDGParser(HTMLParser):
    """Minimal scraper for https://html.duckduckgo.com/html/?q=<query>."""

    _IN_RESULT: ClassVar[frozenset[str]] = frozenset({"a", "span"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._results: list[dict[str, str]] = []
        self._cur: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        classes = (attr_dict.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            href = attr_dict.get("href") or ""
            self._cur = {"title": "", "url": href, "content": ""}
            self._capture_title = True
        elif tag == "a":
            self._capture_title = False
        if tag == "span" and "result__snippet" in classes:
            self._capture_snip = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self._capture_title = False
            if self._cur:
                self._results.append(self._cur)
                self._cur = None
        if tag == "span":
            self._capture_snip = False

    def handle_data(self, data: str) -> None:
        if self._capture_title and self._cur is not None:
            self._cur["title"] += data
        elif self._capture_snip and self._results:
            self._results[-1]["content"] += data


async def _ddg_search(query: str, max_results: int) -> list[dict[str, str]]:
    import asyncio

    def _sync() -> list[dict[str, str]]:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(2 * 1024 * 1024)
        parser = _DDGParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        return parser._results[:max_results]

    return await asyncio.to_thread(_sync)


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------


def _format_results(results: list[dict[str, str]], source: str) -> str:
    if not results:
        return f"No results found. (source: {source})"
    lines: list[str] = [f"Search results via {source}:\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"## {i}. {r['title']}")
        lines.append(r["url"])
        snippet = (r.get("content") or "").strip()
        if snippet:
            lines.append(snippet[:400])
        lines.append("")
    text = "\n".join(lines)
    if len(text) > _MAX_OUTPUT_CHARS:
        text = text[:_MAX_OUTPUT_CHARS] + "\n…[truncated]"
    return text


# ---------------------------------------------------------------------------
# tool
# ---------------------------------------------------------------------------


def _read_tavily_key() -> str | None:
    """Read search.tavily_api_key from ~/.tern/config.json."""
    from tern.core.config import get_config

    try:
        return get_config("search.tavily_api_key") or None
    except Exception:
        return None


class WebSearchTool:
    """Search the web and return ranked text results.

    Uses Tavily if search.tavily_api_key is set in ~/.tern/config.json;
    falls back to DuckDuckGo HTML lite otherwise.
    """

    name = "web_search"
    title = "Web Search"
    description = (
        "Search the web for a query and return top results with titles, "
        "URLs, and snippets. Use for current events, docs lookup, or "
        "any question that needs up-to-date information."
    )
    args_model: type[BaseModel] = WebSearchArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, WebSearchArgs)
        api_key = _read_tavily_key()
        try:
            if api_key:
                results = await _tavily_search(args.query, args.max_results, api_key)
                source = "Tavily"
            else:
                results = await _ddg_search(args.query, args.max_results)
                source = "DuckDuckGo"
        except Exception as exc:  # network errors, parse errors
            return ToolResult(ok=False, content=f"search failed: {exc}", error=str(exc))

        return ToolResult(
            ok=True,
            content=_format_results(results, source),
            metadata={"source": source, "n_results": len(results), "query": args.query},
        )


# Structural check.
from tern.tools.protocol import Tool  # noqa: E402

_: Tool = WebSearchTool()

__all__ = ["WebSearchArgs", "WebSearchTool"]
