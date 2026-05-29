"""Tests for S22 — vision (ImageBlock + screenshot tool + adapter serialization)."""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tern.core.canonical import ImageBlock

# ---------------------------------------------------------------------------
# ScreenshotTool unit tests
# ---------------------------------------------------------------------------

class TestScreenshotTool:
    """Offline tests — mock subprocess, no real screencapture call."""

    def _make_png(self) -> bytes:
        """Minimal 1x1 white PNG."""
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    @pytest.mark.asyncio
    async def test_invoke_ok_returns_image_block(self, tmp_path: Any) -> None:
        from tern.tools.native.screenshot import ScreenshotTool
        from tern.tools.protocol import ToolContext

        png = self._make_png()

        with patch("tern.tools.native.screenshot.capture_screen", return_value=png):
            tool = ScreenshotTool()
            ctx = ToolContext(
                repo_root=tmp_path,
                session_id="s22",
                turn_idx=0,
                mode="default",
            )
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, ctx)

        assert result.ok
        assert "KB PNG" in result.content
        assert len(result.image_blocks) == 1
        img = result.image_blocks[0]
        assert isinstance(img, ImageBlock)
        assert img.media_type == "image/png"
        assert base64.b64decode(img.data_b64) == png

    @pytest.mark.asyncio
    async def test_invoke_failure_returns_error(self, tmp_path: Any) -> None:
        from tern.tools.native.screenshot import ScreenshotTool
        from tern.tools.protocol import ToolContext

        with patch(
            "tern.tools.native.screenshot.capture_screen",
            side_effect=RuntimeError("no display"),
        ):
            tool = ScreenshotTool()
            ctx = ToolContext(
                repo_root=tmp_path,
                session_id="s22",
                turn_idx=0,
                mode="default",
            )
            args = tool.args_model.model_validate({})
            result = await tool.invoke(args, ctx)

        assert not result.ok
        assert "no display" in (result.error or "")
        assert len(result.image_blocks) == 0

    @pytest.mark.asyncio
    async def test_invoke_with_region(self, tmp_path: Any) -> None:
        from tern.tools.native.screenshot import ScreenshotTool
        from tern.tools.protocol import ToolContext

        png = self._make_png()
        with patch("tern.tools.native.screenshot.capture_screen", return_value=png) as mock_cap:
            tool = ScreenshotTool()
            ctx = ToolContext(repo_root=tmp_path, session_id="s22", turn_idx=0, mode="default")
            args = tool.args_model.model_validate({"region": "0,0,800,600"})
            result = await tool.invoke(args, ctx)

        assert result.ok
        assert "region=0,0,800,600" in result.content
        mock_cap.assert_called_once_with(window=None, region="0,0,800,600")

    def test_tool_protocol_conformance(self) -> None:
        """ScreenshotTool must satisfy the Tool Protocol."""
        from tern.tools.native.screenshot import ScreenshotTool
        from tern.tools.protocol import Tool
        assert isinstance(ScreenshotTool(), Tool)

    def test_args_model_extra_forbidden(self) -> None:
        from pydantic import ValidationError

        from tern.tools.native.screenshot import ScreenshotArgs
        with pytest.raises(ValidationError):
            ScreenshotArgs.model_validate({"unknown_field": True})


# ---------------------------------------------------------------------------
# capture_screen dispatch tests
# ---------------------------------------------------------------------------

class TestCaptureScreen:
    def _make_png(self) -> bytes:
        return b"\x89PNG\r\n\x1a\nminimal"

    def test_macos_dispatch(self) -> None:
        from tern.tools.native.screenshot import capture_screen
        png = self._make_png()
        with patch("platform.system", return_value="Darwin"), \
             patch("tern.tools.native.screenshot._capture_macos", return_value=png) as m:
            result = capture_screen()
        assert result == png
        m.assert_called_once_with(None, None)

    def test_linux_dispatch(self) -> None:
        from tern.tools.native.screenshot import capture_screen
        png = self._make_png()
        with patch("platform.system", return_value="Linux"), \
             patch("tern.tools.native.screenshot._capture_linux", return_value=png) as m:
            result = capture_screen()
        assert result == png
        m.assert_called_once()

    def test_unsupported_platform(self) -> None:
        from tern.tools.native.screenshot import capture_screen
        with patch("platform.system", return_value="Windows"), \
             pytest.raises(RuntimeError, match="not supported"):
            capture_screen()


# ---------------------------------------------------------------------------
# Bedrock Anthropic adapter — ImageBlock serialization
# ---------------------------------------------------------------------------

class TestBedrockAnthropicImageBlock:
    def _make_image_msg(self) -> Any:
        from tern.core.canonical import (
            SCHEMA_VERSION,
            CanonicalMessage,
            ImageBlock,
            Metadata,
            TextBlock,
        )
        return CanonicalMessage(
            role="user",
            content=(
                TextBlock(text="what do you see?"),
                ImageBlock(media_type="image/png", data_b64="aGVsbG8="),
            ),
            metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
        )

    def test_image_block_in_user_message(self) -> None:
        from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter
        msg = self._make_image_msg()
        wire = BedrockAnthropicAdapter.to_wire((msg,))
        content = wire["messages"][0]["content"]
        assert any(b.get("type") == "text" for b in content)
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 1
        img = image_blocks[0]
        assert img["source"]["type"] == "base64"
        assert img["source"]["media_type"] == "image/png"
        assert img["source"]["data"] == "aGVsbG8="

    def test_image_block_standalone(self) -> None:
        from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter
        from tern.core.canonical import SCHEMA_VERSION, CanonicalMessage, ImageBlock, Metadata
        msg = CanonicalMessage(
            role="user",
            content=(ImageBlock(media_type="image/jpeg", data_b64="dGVzdA=="),),
            metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
        )
        wire = BedrockAnthropicAdapter.to_wire((msg,))
        content = wire["messages"][0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["media_type"] == "image/jpeg"


# ---------------------------------------------------------------------------
# Bedrock Nova adapter — ImageBlock serialization
# ---------------------------------------------------------------------------

class TestBedrockNovaImageBlock:
    def test_image_block_decoded_to_bytes(self) -> None:
        from tern.adapters.bedrock_nova import BedrockNovaAdapter
        from tern.core.canonical import SCHEMA_VERSION, CanonicalMessage, ImageBlock, Metadata
        raw = b"\x89PNG\r\n\x1a\ntest"
        b64 = base64.b64encode(raw).decode()
        msg = CanonicalMessage(
            role="user",
            content=(ImageBlock(media_type="image/png", data_b64=b64),),
            metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
        )
        wire = BedrockNovaAdapter.to_wire((msg,))
        content = wire["messages"][0]["content"]
        assert len(content) == 1
        img_block = content[0]
        assert "image" in img_block
        assert img_block["image"]["format"] == "png"
        assert img_block["image"]["source"]["bytes"] == raw

    def test_image_alongside_text(self) -> None:
        from tern.adapters.bedrock_nova import BedrockNovaAdapter
        from tern.core.canonical import (
            SCHEMA_VERSION,
            CanonicalMessage,
            ImageBlock,
            Metadata,
            TextBlock,
        )
        raw = b"fakeimage"
        b64 = base64.b64encode(raw).decode()
        msg = CanonicalMessage(
            role="user",
            content=(
                TextBlock(text="describe this"),
                ImageBlock(media_type="image/jpeg", data_b64=b64),
            ),
            metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
        )
        wire = BedrockNovaAdapter.to_wire((msg,))
        content = wire["messages"][0]["content"]
        assert any("text" in b for b in content)
        img_blocks = [b for b in content if "image" in b]
        assert len(img_blocks) == 1
        assert img_blocks[0]["image"]["format"] == "jpeg"


# ---------------------------------------------------------------------------
# Loop: image injection into follow-up user message
# ---------------------------------------------------------------------------

class TestLoopImageInjection:
    """Verify that image_blocks from a ToolResult become a follow-up user message."""

    @pytest.mark.asyncio
    async def test_image_blocks_injected_as_user_message(self, tmp_path: Any) -> None:
        """Smoke test: a tool returning image_blocks causes a follow-up user message."""
        from pydantic import BaseModel, ConfigDict

        from tern.core.canonical import ImageBlock, TextBlock, ToolCallBlock
        from tern.core.loop import run_turn
        from tern.core.turn import Turn, TurnPurpose
        from tern.tools import Registry
        from tern.tools.protocol import ToolAnnotations, ToolContext, ToolResult

        raw_png = b"\x89PNG\r\n\x1a\ntest"
        b64_png = base64.b64encode(raw_png).decode()

        class _FakeArgs(BaseModel):
            model_config = ConfigDict(extra="forbid")

        class _FakeTool:
            name = "snap"
            title = "Snap"
            description = "fake screenshot tool"
            args_model: type[BaseModel] = _FakeArgs
            annotations = ToolAnnotations(read_only=True, idempotent=False)

            async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
                return ToolResult(
                    ok=True,
                    content="snap ok",
                    image_blocks=(ImageBlock(media_type="image/png", data_b64=b64_png),),
                )

        # First response: calls snap; second response: final text
        call_block = ToolCallBlock(id="tc1", name="snap", args={})
        from tern.core.canonical import (
            SCHEMA_VERSION,
            CanonicalMessage,
            Cost,
            Metadata,
            ProviderResponse,
        )

        first_response = ProviderResponse(
            message=CanonicalMessage(
                role="assistant",
                content=(call_block,),
                metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
            ),
            stop_reason="tool_use",
            cost=Cost(0, 0, 0.0, 0.0),
            raw_id="r1",
        )
        final_response = ProviderResponse(
            message=CanonicalMessage(
                role="assistant",
                content=(TextBlock(text="I see a test image"),),
                metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
            ),
            stop_reason="end_turn",
            cost=Cost(0, 0, 0.0, 0.0),
            raw_id="r2",
        )

        call_count = 0

        class _FakeAdapter:
            model_id = "fake-vision-model"
            capabilities = MagicMock(vision=True, tool_use=True)

            async def complete(self, messages: Any, tools: Any, **kw: Any) -> ProviderResponse:
                nonlocal call_count
                call_count += 1
                # On second call, verify the vision user message was injected
                if call_count == 2:
                    roles = [m.role for m in messages]
                    vision_msgs = [
                        m for m in messages
                        if m.role == "user" and any(isinstance(b, ImageBlock) for b in m.content)
                    ]
                    assert vision_msgs, f"Expected vision user message, got roles: {roles}"
                return first_response if call_count == 1 else final_response

        registry = Registry([_FakeTool()])  # type: ignore[list-item]
        turn = Turn(
            id="test-s22-turn",
            session_id="test-s22",
            idx=0,
            purpose=TurnPurpose.CODE,
            messages=(
                CanonicalMessage(
                    role="user",
                    content=(TextBlock(text="take a screenshot"),),
                    metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
                ),
            ),
            repo_root=tmp_path,
            registry=registry,
        )

        events = []
        async for ev in run_turn(turn, _FakeAdapter()):  # type: ignore[arg-type]
            events.append(ev)

        assert call_count == 2
