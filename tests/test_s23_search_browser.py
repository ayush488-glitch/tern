"""Tests for S23 — web_search + browser tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> Any:
    from tern.tools.protocol import ToolContext
    return ToolContext(repo_root=tmp_path, session_id="s23", turn_idx=0, mode="default")


# ---------------------------------------------------------------------------
# WebSearchTool — unit tests (no real network)
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_ddg_fallback_on_no_key(self, tmp_path: Path) -> None:
        from tern.tools.native.web_search import WebSearchTool

        fake_results = [
            {"title": "Example", "url": "https://example.com", "content": "An example site."}
        ]
        with patch("tern.tools.native.web_search._read_tavily_key", return_value=None), \
             patch("tern.tools.native.web_search._ddg_search", new=AsyncMock(return_value=fake_results)):
            tool = WebSearchTool()
            args = tool.args_model.model_validate({"query": "test search"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "DuckDuckGo" in result.content
        assert "Example" in result.content
        assert result.metadata["source"] == "DuckDuckGo"  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_tavily_when_key_present(self, tmp_path: Path) -> None:
        from tern.tools.native.web_search import WebSearchTool

        fake_results = [
            {"title": "Docs", "url": "https://docs.example.com", "content": "Official docs."}
        ]
        with patch("tern.tools.native.web_search._read_tavily_key", return_value="fake-key"), \
             patch(
                 "tern.tools.native.web_search._tavily_search",
                 new=AsyncMock(return_value=fake_results),
             ):
            tool = WebSearchTool()
            args = tool.args_model.model_validate({"query": "python docs"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "Tavily" in result.content
        assert "Docs" in result.content

    @pytest.mark.asyncio
    async def test_network_error_returns_failure(self, tmp_path: Path) -> None:
        from tern.tools.native.web_search import WebSearchTool

        with patch("tern.tools.native.web_search._read_tavily_key", return_value=None), \
             patch(
                 "tern.tools.native.web_search._ddg_search",
                 new=AsyncMock(side_effect=ConnectionError("timeout")),
             ):
            tool = WebSearchTool()
            args = tool.args_model.model_validate({"query": "something"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert not result.ok
        assert "timeout" in (result.error or "")

    def test_args_extra_forbidden(self) -> None:
        from pydantic import ValidationError

        from tern.tools.native.web_search import WebSearchArgs

        with pytest.raises(ValidationError):
            WebSearchArgs.model_validate({"query": "x", "unknown": True})

    def test_tool_protocol_conformance(self) -> None:
        from tern.tools.native.web_search import WebSearchTool
        from tern.tools.protocol import Tool
        assert isinstance(WebSearchTool(), Tool)

    @pytest.mark.asyncio
    async def test_empty_results_message(self, tmp_path: Path) -> None:
        from tern.tools.native.web_search import WebSearchTool

        with patch("tern.tools.native.web_search._read_tavily_key", return_value=None), \
             patch("tern.tools.native.web_search._ddg_search", new=AsyncMock(return_value=[])):
            tool = WebSearchTool()
            args = tool.args_model.model_validate({"query": "zzznoresults"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "No results" in result.content

    def test_max_results_cap(self) -> None:
        from pydantic import ValidationError

        from tern.tools.native.web_search import WebSearchArgs

        with pytest.raises(ValidationError):
            WebSearchArgs.model_validate({"query": "x", "max_results": 11})


# ---------------------------------------------------------------------------
# _format_results
# ---------------------------------------------------------------------------


class TestFormatResults:
    def test_basic_format(self) -> None:
        from tern.tools.native.web_search import _format_results

        results = [{"title": "T1", "url": "https://a.com", "content": "snippet"}]
        out = _format_results(results, "Tavily")
        assert "T1" in out
        assert "https://a.com" in out
        assert "snippet" in out

    def test_truncated_at_8000(self) -> None:
        from tern.tools.native.web_search import _format_results

        # 20 results with long content — enough to exceed 8000 chars
        results = [
            {"title": f"Title {i}", "url": f"https://example.com/{i}", "content": "x" * 400}
            for i in range(20)
        ]
        out = _format_results(results, "DDG")
        assert len(out) <= 8100
        assert "truncated" in out


# ---------------------------------------------------------------------------
# acc_to_text
# ---------------------------------------------------------------------------


class TestAccToText:
    def test_basic_node(self) -> None:
        from tern.tools.native.browser import _acc_to_text

        node = {"role": "button", "name": "Submit", "children": []}
        out = _acc_to_text(node)
        assert "[button]" in out
        assert "'Submit'" in out

    def test_nested(self) -> None:
        from tern.tools.native.browser import _acc_to_text

        node = {
            "role": "main",
            "name": "",
            "children": [
                {"role": "heading", "name": "Hello", "children": []},
                {"role": "link", "name": "Click me", "children": []},
            ],
        }
        out = _acc_to_text(node)
        assert "heading" in out
        assert "Hello" in out
        assert "Click me" in out

    def test_none_node(self) -> None:
        from tern.tools.native.browser import _acc_to_text
        assert _acc_to_text(None) == ""


# ---------------------------------------------------------------------------
# BrowserNavigateTool
# ---------------------------------------------------------------------------


class TestBrowserNavigateTool:
    def _mock_session(self, url: str = "https://example.com", title: str = "Example") -> MagicMock:
        s = MagicMock()
        s.navigate = AsyncMock(return_value={"url": url, "title": title})
        return s

    @pytest.mark.asyncio
    async def test_navigate_ok(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserNavigateTool

        with patch("tern.tools.native.browser._get_session", return_value=self._mock_session()):
            tool = BrowserNavigateTool()
            args = tool.args_model.model_validate({"url": "https://example.com"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "example.com" in result.content
        assert "Example" in result.content

    @pytest.mark.asyncio
    async def test_navigate_error(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserNavigateTool

        session = MagicMock()
        session.navigate = AsyncMock(side_effect=RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserNavigateTool()
            args = tool.args_model.model_validate({"url": "https://no-such-host.invalid"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert not result.ok
        assert "ERR_NAME_NOT_RESOLVED" in (result.error or "")

    def test_protocol_conformance(self) -> None:
        from tern.tools.native.browser import BrowserNavigateTool
        from tern.tools.protocol import Tool
        assert isinstance(BrowserNavigateTool(), Tool)


# ---------------------------------------------------------------------------
# BrowserSnapshotTool
# ---------------------------------------------------------------------------


class TestBrowserSnapshotTool:
    @pytest.mark.asyncio
    async def test_snapshot_returns_text(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserSnapshotTool

        session = MagicMock()
        session.snapshot = AsyncMock(return_value="[button] 'Submit'\n[link] 'Home'")
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserSnapshotTool()
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "Submit" in result.content

    @pytest.mark.asyncio
    async def test_snapshot_empty_page(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserSnapshotTool

        session = MagicMock()
        session.snapshot = AsyncMock(return_value="   ")
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserSnapshotTool()
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "empty" in result.content

    @pytest.mark.asyncio
    async def test_snapshot_truncated(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserSnapshotTool

        session = MagicMock()
        session.snapshot = AsyncMock(return_value="x" * 15_000)
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserSnapshotTool()
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "truncated" in result.content
        assert len(result.content) <= 12_100


# ---------------------------------------------------------------------------
# BrowserClickTool
# ---------------------------------------------------------------------------


class TestBrowserClickTool:
    @pytest.mark.asyncio
    async def test_click_ok(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserClickTool

        session = MagicMock()
        session.click = AsyncMock()
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserClickTool()
            args = tool.args_model.model_validate({"selector": "button#submit"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "button#submit" in result.content

    @pytest.mark.asyncio
    async def test_click_timeout(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserClickTool

        session = MagicMock()
        session.click = AsyncMock(side_effect=TimeoutError("Timeout 10s exceeded."))
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserClickTool()
            args = tool.args_model.model_validate({"selector": "#gone"})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert not result.ok
        assert "Timeout" in (result.error or "")

    def test_destructive_flag(self) -> None:
        from tern.tools.native.browser import BrowserClickTool
        assert BrowserClickTool().annotations.destructive is True


# ---------------------------------------------------------------------------
# BrowserTypeTool
# ---------------------------------------------------------------------------


class TestBrowserTypeTool:
    @pytest.mark.asyncio
    async def test_type_ok(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserTypeTool

        session = MagicMock()
        session.type_text = AsyncMock()
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserTypeTool()
            args = tool.args_model.model_validate(
                {"selector": "input#search", "text": "hello world", "clear": True}
            )
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "11 chars" in result.content
        session.type_text.assert_called_once_with("input#search", "hello world", True)

    def test_destructive_flag(self) -> None:
        from tern.tools.native.browser import BrowserTypeTool
        assert BrowserTypeTool().annotations.destructive is True


# ---------------------------------------------------------------------------
# BrowserVisionTool
# ---------------------------------------------------------------------------


class TestBrowserVisionTool:
    def _make_png(self) -> bytes:
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    @pytest.mark.asyncio
    async def test_vision_returns_image_block(self, tmp_path: Path) -> None:
        import base64

        from tern.core.canonical import ImageBlock
        from tern.tools.native.browser import BrowserVisionTool

        png = self._make_png()
        session = MagicMock()
        session.screenshot_png = AsyncMock(return_value=png)
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserVisionTool()
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert result.ok
        assert "KB PNG" in result.content
        assert len(result.image_blocks) == 1
        img = result.image_blocks[0]
        assert isinstance(img, ImageBlock)
        assert img.media_type == "image/png"
        assert base64.b64decode(img.data_b64) == png

    @pytest.mark.asyncio
    async def test_vision_error(self, tmp_path: Path) -> None:
        from tern.tools.native.browser import BrowserVisionTool

        session = MagicMock()
        session.screenshot_png = AsyncMock(side_effect=RuntimeError("no page"))
        with patch("tern.tools.native.browser._get_session", return_value=session):
            tool = BrowserVisionTool()
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, _ctx(tmp_path))

        assert not result.ok
        assert "no page" in (result.error or "")

    def test_non_destructive(self) -> None:
        from tern.tools.native.browser import BrowserVisionTool
        assert BrowserVisionTool().annotations.destructive is False
        assert BrowserVisionTool().annotations.read_only is True
