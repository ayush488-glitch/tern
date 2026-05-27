"""Native tools — Tern's first sibling under the unified Tool surface.

Per ADR-0003 §native, native tools are pure functions wrapped to obey the Tool
Protocol. They live here so the registry can autoload them at S11 without
import gymnastics.
"""

from __future__ import annotations

from tern.tools.native.edit_block import EditBlockTool
from tern.tools.native.read_file import ReadFileTool

__all__ = ["EditBlockTool", "ReadFileTool"]
