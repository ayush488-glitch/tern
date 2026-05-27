"""web_fetch — D5 (browser-shaped) tool v0.

S13 wires the *slot* for D5. Real browser-use / Playwright is heavy and pulls
a Chromium binary; we'd rather ship the surface and the gate today and swap
the engine later. So v0 is an HTTP fetch + a brutally simple HTML→text
reduction. Same Tool Protocol surface, same gate, same artifact path. The
model can already say "open hn, summarize the top post" and get back a
useful slice of the page.

Why not skip and wait for the real browser? D5's value is that web is one
of N tools the gate sees uniformly. Landing the slot early means S14
hardening (timeouts, redaction, audit) covers it; swapping the body to
browser-use later is an isolated change.

Pitfalls baked in:
- 5MB body cap (open_world tools should never blow context).
- Bedrock-style 10s connect/15s read timeout.
- HTML reducer kills <script>/<style>; uses HTMLParser, not regex.
- text content is escaped + length-capped before returning to the model.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tern.tools.protocol import ToolAnnotations, ToolContext, ToolResult

_USER_AGENT = "tern/0.0.1 (+https://github.com/antern-dev/tern)"
_MAX_BYTES = 5 * 1024 * 1024  # 5MB
_MAX_TEXT_CHARS = 16_000  # what the model sees; rest stashed in metadata


# ---------------------------------------------------------------------------
# args
# ---------------------------------------------------------------------------


class WebFetchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="Absolute http(s) URL to fetch.")
    timeout_s: float = Field(default=15.0, ge=1.0, le=60.0, description="Read timeout.")

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        scheme = urlparse(v).scheme
        if scheme not in {"http", "https"}:
            raise ValueError(f"web_fetch only allows http(s); got {scheme!r}")
        return v


# ---------------------------------------------------------------------------
# HTML→text
# ---------------------------------------------------------------------------


class _Stripper(HTMLParser):
    """Lift visible text from HTML. Drops <script>/<style>/<noscript> blocks
    entirely; collapses runs of whitespace; treats <br>/<p>/<li> as line breaks."""

    _BLOCK_DROP: ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "noscript", "template"}
    )
    _BLOCK_BREAK: ClassVar[frozenset[str]] = frozenset(
        {
            "br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
            "section", "article", "header", "footer", "nav", "ul", "ol",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []
        self._depth_skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_DROP:
            self._depth_skip += 1
        if tag in self._BLOCK_BREAK:
            self._buf.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_DROP and self._depth_skip > 0:
            self._depth_skip -= 1

    def handle_data(self, data: str) -> None:
        if self._depth_skip == 0:
            self._buf.append(data)

    def text(self) -> str:
        joined = "".join(self._buf)
        # collapse runs of whitespace per line; keep blank-line breaks
        lines = [" ".join(ln.split()) for ln in joined.splitlines()]
        out: list[str] = []
        for ln in lines:
            if ln or (out and out[-1]):
                out.append(ln)
        return "\n".join(out).strip()


def _html_to_text(body: bytes, charset: str | None) -> str:
    text = body.decode(charset or "utf-8", errors="replace")
    p = _Stripper()
    p.feed(text)
    return p.text()


# ---------------------------------------------------------------------------
# tool
# ---------------------------------------------------------------------------


class WebFetchTool:
    """Fetch a URL and return a text slice.

    `read_only` from the local filesystem's perspective; `open_world` because
    the URL points outside the sandbox. The gate uses these two flags
    together to decide whether to prompt (default mode prompts on
    open_world+destructive; read_only+open_world is allowed in default).
    """

    name = "web_fetch"
    title = "Fetch a URL"
    description = (
        "Fetch an http(s) URL and return its main text content. HTML is "
        "stripped to readable text; non-HTML bodies are returned as-is up "
        "to a 5MB cap. Use this for browsing pages the user references; "
        "for structured APIs, prefer an MCP tool when one is available."
    )
    args_model: type[BaseModel] = WebFetchArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, WebFetchArgs)
        try:
            payload = await _fetch(args.url, args.timeout_s)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return ToolResult(ok=False, content=f"fetch failed: {exc}", error=str(exc))

        body = payload["body"]
        ctype = payload["content_type"]
        if "html" in ctype.lower():
            text = _html_to_text(body, payload["charset"])
        else:
            text = body.decode(payload["charset"] or "utf-8", errors="replace")

        truncated = len(text) > _MAX_TEXT_CHARS
        head = text[:_MAX_TEXT_CHARS]
        suffix = "\n\n…[truncated]" if truncated else ""
        rendered = f"# {args.url}\nstatus={payload['status']} ctype={ctype}\n\n{head}{suffix}"

        return ToolResult(
            ok=True,
            content=rendered,
            metadata={
                "url": args.url,
                "status": payload["status"],
                "content_type": ctype,
                "bytes": len(body),
                "truncated": truncated,
                "full_text_chars": len(text),
            },
        )


# ---------------------------------------------------------------------------
# fetch (kept separate so tests can monkeypatch it)
# ---------------------------------------------------------------------------


async def _fetch(url: str, timeout_s: float) -> dict[str, Any]:
    """Run urllib in a thread so the event loop doesn't block."""
    import asyncio

    return await asyncio.to_thread(_fetch_sync, url, timeout_s)


def _fetch_sync(url: str, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read(_MAX_BYTES + 1)
        if len(body) > _MAX_BYTES:
            raise ValueError(f"response exceeds {_MAX_BYTES} byte cap")
        ctype_hdr = resp.headers.get("Content-Type", "")
        charset: str | None = None
        for part in ctype_hdr.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                charset = part.split("=", 1)[1].strip().strip('"')
        return {
            "status": resp.status,
            "content_type": ctype_hdr.split(";")[0].strip() or "application/octet-stream",
            "charset": charset,
            "body": body,
        }


__all__ = ["WebFetchArgs", "WebFetchTool"]
