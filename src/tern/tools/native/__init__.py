"""Native tools — Tern's first sibling under the unified Tool surface.

Per ADR-0003 §native, native tools are pure functions wrapped to obey the Tool
Protocol. They live here so the registry can autoload them at S11 without
import gymnastics.
"""

from __future__ import annotations

from tern.tools.native.bash import BashTool
from tern.tools.native.edit_block import EditBlockTool
from tern.tools.native.glob_tool import GlobTool
from tern.tools.native.grep_tool import GrepTool
from tern.tools.native.memory_tool import MemoryTool
from tern.tools.native.notes_append import NotesAppendTool
from tern.tools.native.read_file import ReadFileTool
from tern.tools.native.skill_manage import SkillManageTool
from tern.tools.native.web_fetch import WebFetchTool
from tern.tools.native.write_file import WriteFileTool

__all__ = [
    "BashTool",
    "EditBlockTool",
    "GlobTool",
    "GrepTool",
    "MemoryTool",
    "NotesAppendTool",
    "ReadFileTool",
    "SkillManageTool",
    "WebFetchTool",
    "WriteFileTool",
]
