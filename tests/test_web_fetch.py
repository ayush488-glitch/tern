"""Tests for the web_fetch tool (D5 v0).

We don't hit the network. The tool's _fetch_sync is the seam — every test
monkeypatches it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from tern.tools.native import web_fetch
from tern.tools.native.web_fetch import WebFetchArgs, WebFetchTool
from tern.tools.protocol import ToolContext


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        repo_root=tmp_path, session_id="s", turn_idx=0, mode="default"
    )


# ---------------------------------------------------------------------------
# args
# ---------------------------------------------------------------------------


def test_args_rejects_non_http() -> None:
    with pytest.raises(ValidationError):
        WebFetchArgs(url="file:///etc/passwd")
    with pytest.raises(ValidationError):
        WebFetchArgs(url="ftp://example.com")


def test_args_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        WebFetchArgs(url="http://example.com", oops=1)  # type: ignore[call-arg]


def test_args_timeout_clamped() -> None:
    with pytest.raises(ValidationError):
        WebFetchArgs(url="http://x", timeout_s=0.5)


# ---------------------------------------------------------------------------
# html stripping
# ---------------------------------------------------------------------------


def test_html_strips_script_and_style() -> None:
    html = (
        b"<html><head><style>x{}</style><script>alert(1)</script></head>"
        b"<body><h1>Hi</h1><p>Hello <b>world</b>.</p></body></html>"
    )
    text = web_fetch._html_to_text(html, "utf-8")
    assert "alert" not in text
    assert "x{}" not in text
    assert "Hi" in text and "Hello world." in text


def test_html_collapses_whitespace() -> None:
    html = b"<p>foo   bar</p><p>baz</p>"
    text = web_fetch._html_to_text(html, "utf-8")
    assert "foo bar" in text
    assert "baz" in text


# ---------------------------------------------------------------------------
# invoke
# ---------------------------------------------------------------------------


def _stub_fetch(body: bytes, ctype: str = "text/html"):
    def fake(url: str, timeout_s: float):  # type: ignore[no-untyped-def]
        return {
            "status": 200,
            "content_type": ctype,
            "charset": "utf-8",
            "body": body,
        }

    return fake


def test_invoke_html(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        web_fetch, "_fetch_sync", _stub_fetch(b"<h1>Top story</h1>", "text/html")
    )
    tool = WebFetchTool()
    res = asyncio.run(tool.invoke(WebFetchArgs(url="http://x"), _ctx(tmp_path)))
    assert res.ok
    assert "Top story" in res.content
    assert res.metadata["status"] == 200
    assert res.metadata["content_type"] == "text/html"
    assert res.metadata["truncated"] is False


def test_invoke_plaintext(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        web_fetch, "_fetch_sync", _stub_fetch(b"line1\nline2", "text/plain")
    )
    tool = WebFetchTool()
    res = asyncio.run(tool.invoke(WebFetchArgs(url="http://x"), _ctx(tmp_path)))
    assert res.ok
    assert "line1" in res.content and "line2" in res.content


def test_invoke_truncates_huge_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    big = b"a " * 20_000  # ~40k chars after decode
    monkeypatch.setattr(web_fetch, "_fetch_sync", _stub_fetch(big, "text/plain"))
    tool = WebFetchTool()
    res = asyncio.run(tool.invoke(WebFetchArgs(url="http://x"), _ctx(tmp_path)))
    assert res.ok
    assert res.metadata["truncated"] is True
    assert "[truncated]" in res.content


def test_invoke_handles_fetch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(url: str, timeout_s: float):  # type: ignore[no-untyped-def]
        raise TimeoutError("read timed out")

    monkeypatch.setattr(web_fetch, "_fetch_sync", boom)
    tool = WebFetchTool()
    res = asyncio.run(tool.invoke(WebFetchArgs(url="http://x"), _ctx(tmp_path)))
    assert not res.ok
    assert "timed out" in (res.error or "")


def test_annotations_read_only_open_world() -> None:
    tool = WebFetchTool()
    assert tool.annotations.read_only is True
    assert tool.annotations.open_world is True
    assert tool.annotations.destructive is False
