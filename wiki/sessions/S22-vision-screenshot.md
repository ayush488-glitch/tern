---
title: S22 — Vision (ImageBlock + Screenshot Tool)
type: session
created: 2026-05-29
updated: 2026-05-29
sources: [decisions/adr-0011-cognitive-routing-and-recall.md]
tags: [tern, s22, vision, screenshot, imageblock, bedrock-nova]
---

# S22 — Vision: ImageBlock + Screenshot Tool

## What was built

### ToolResult.image_blocks (protocol.py)
Added `image_blocks: tuple[Any, ...] = field(default_factory=tuple)` to `ToolResult`.
Tools that produce images (screenshot, browser, future camera) put `ImageBlock` objects here.
Kept `content: str` as the text description fallback.

### Loop image injection (loop.py)
After each tool batch executes, the loop collects `pending_images` from all tool results.
If any exist, a follow-up `role="user"` message is appended containing a `TextBlock` label
plus the `ImageBlock`s. Both adapters handle `ImageBlock` in user-role content correctly.
This respects ADR-0002 (vision content goes through the canonical message log, not a side channel).

### bedrock_nova.py — ImageBlock wiring
Replaced the `# ImageBlock support deferred to S17` stub with real serialization.
Nova's Converse API requires raw bytes, not base64, so `_capture_macos` decodes `data_b64`
before building the `{"image": {"format": ..., "source": {"bytes": raw}}}` block.

### bedrock_anthropic.py
Already had ImageBlock serialization from an earlier pass. No change needed — tests confirm it.

### screenshot tool (tools/native/screenshot.py)
Platform dispatch: macOS via `screencapture -x -t png`, Linux via `grim` then `gnome-screenshot`.
Args: `window` (title filter, macOS only), `region` ("x,y,w,h", macOS only).
Returns `ToolResult(ok=True, content="<size> KB PNG", image_blocks=(ImageBlock(...),))`.
Registered in `cli.py` alongside ProcTool.

## Numbers

| Metric | Value |
|--------|-------|
| ruff | 0 errors (72 files) |
| mypy --strict | 0 errors (72 files) |
| pytest | 464/464 passed, 1 skipped |
| new tests | +13 (test_s22_vision.py) |
| new/modified files | 5 |

## Files changed

| File | Change |
|------|--------|
| `src/tern/tools/protocol.py` | added `image_blocks` to `ToolResult` |
| `src/tern/core/loop.py` | pending_images collection + follow-up user message injection |
| `src/tern/adapters/bedrock_nova.py` | ImageBlock serialization (base64 decode → raw bytes) |
| `src/tern/tools/native/screenshot.py` | new tool: platform-aware screencapture |
| `src/tern/cli.py` | registered ScreenshotTool |
| `tests/test_s22_vision.py` | 13 new tests |

## Key decisions

1. **Follow-up user message** over tool_result embedding. Anthropic and Nova have different
   tool_result content shapes; injecting images as a separate user message works uniformly
   on both adapters and keeps tool_result content as a plain string.

2. **Nova: decode base64 to raw bytes**. Boto3's Converse API rejects base64 strings;
   it wants Python `bytes` objects in the `source.bytes` field.

3. **`capture_screen` is a standalone function**, not a method. Makes it trivially patchable
   in tests without going through the class.

4. **macOS: temp file, not stdout**. `screencapture -` (stdout mode) is unreliable on some
   macOS versions. Write to a temp file, read, delete.

## What's next

S23 per ADR-0011 or roadmap — check `wiki/roadmap/14-session-plan.md`.
