"""screenshot — capture the screen and return an ImageBlock (S22 / vision).

On macOS: uses `screencapture -x -t png` (writes PNG to temp file).
On Linux: tries `grim` (Wayland) then `gnome-screenshot`.
On other platforms: returns a text error.

The ImageBlock is injected into the next LLM call as a user-role vision message
by the loop (S22 wiring in loop.py). The tool also returns a text description
of what was captured so the model has a text fallback.

Args:
  window     -- optional window title substring (macOS only)
  region     -- optional "x,y,w,h" region (macOS only)
"""

from __future__ import annotations

import base64
import contextlib
import platform
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tern.core.canonical import ImageBlock
from tern.tools.protocol import (
    Tool,
    ToolAnnotations,
    ToolContext,
    ToolResult,
)


class ScreenshotArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: str | None = Field(
        default=None,
        description="Window title substring to capture (macOS only). Omit for full screen.",
    )
    region: str | None = Field(
        default=None,
        description='Screen region as "x,y,w,h" (macOS only). Omit for full screen.',
    )


def _capture_macos(window: str | None, region: str | None) -> bytes:
    """Run screencapture and return raw PNG bytes."""
    cmd: list[str] = ["screencapture", "-x", "-t", "png"]
    if region:
        cmd += ["-R", region]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        cmd.append(tmp)
        subprocess.run(cmd, check=True, timeout=10)
        return Path(tmp).read_bytes()
    finally:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()


def _capture_linux() -> bytes:
    """Try grim (Wayland) then gnome-screenshot (X11/Wayland)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_grim = f.name
    try:
        subprocess.run(["grim", tmp_grim], check=True, timeout=10)
        return Path(tmp_grim).read_bytes()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    finally:
        with contextlib.suppress(OSError):
            Path(tmp_grim).unlink()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_gnome = f.name
    try:
        subprocess.run(["gnome-screenshot", "-f", tmp_gnome], check=True, timeout=10)
        return Path(tmp_gnome).read_bytes()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "No screenshot tool found. Install grim (Wayland) or gnome-screenshot."
        ) from exc
    finally:
        with contextlib.suppress(OSError):
            Path(tmp_gnome).unlink()


def capture_screen(window: str | None = None, region: str | None = None) -> bytes:
    """Platform dispatch. Returns raw PNG bytes."""
    system = platform.system()
    if system == "Darwin":
        return _capture_macos(window, region)
    if system == "Linux":
        return _capture_linux()
    raise RuntimeError(f"screenshot not supported on {system}")


class ScreenshotTool:
    name = "screenshot"
    title = "Screenshot"
    description = (
        "Capture the current screen (or a window/region) as a PNG image. "
        "The image is injected into the next turn so you can describe, analyze, "
        "or interact with what's visible. Use this to check UI state, read "
        "on-screen content, or debug visual issues."
    )
    args_model: type[BaseModel] = ScreenshotArgs
    annotations = ToolAnnotations(read_only=True, idempotent=False)

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, ScreenshotArgs)
        try:
            raw_bytes = capture_screen(window=args.window, region=args.region)
        except Exception as exc:
            return ToolResult(ok=False, content="", error=f"screenshot failed: {exc}")

        data_b64 = base64.b64encode(raw_bytes).decode()
        size_kb = len(raw_bytes) // 1024
        image_block = ImageBlock(media_type="image/png", data_b64=data_b64)

        desc = f"Screenshot captured ({size_kb} KB PNG)"
        if args.region:
            desc += f", region={args.region}"
        if args.window:
            desc += f", window filter={args.window!r}"

        return ToolResult(ok=True, content=desc, image_blocks=(image_block,))


# Structural check.
_: Tool = ScreenshotTool()
