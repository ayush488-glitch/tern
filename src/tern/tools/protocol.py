"""Tool Protocol — the single concept M3 and M1 import.

Per ADR-0003:
  - One Protocol, three sibling implementations (native, browser, MCP).
  - Pydantic v2 generates JSON Schema from Python types; we never write
    schema twice.
  - Annotations follow MCP vocabulary (`destructive`, `idempotent`,
    `read_only`, `open_world`); the same gate reads them regardless of
    where the tool came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from tern.core.canonical import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolAnnotations:
    """MCP-derived annotation vocabulary, applied uniformly."""

    destructive: bool = False
    idempotent: bool = True
    read_only: bool = False
    open_world: bool = False


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Per-call invocation context. Frozen; Tools must NOT mutate.

    `repo_root` enforces sandboxed file writes (ADR-0003 §sandbox-boundaries).
    `mode` is propagated from the CLI flag so the gate at call site agrees with
    the gate at registry-list time.
    """

    repo_root: Path
    session_id: str
    turn_idx: int
    mode: str = "default"  # one of "safe" | "default" | "yolo"

    def resolve_under_repo(self, candidate: str | Path) -> Path:
        """Resolve `candidate` against repo_root, refusing escape via `..`.

        The model can pass relative or absolute paths; both must end up
        inside repo_root. ~ expands explicitly via the caller, not here.
        """
        p = Path(candidate)
        full = p.resolve() if p.is_absolute() else (self.repo_root / p).resolve()
        root = self.repo_root.resolve()
        try:
            full.relative_to(root)
        except ValueError as exc:
            raise PermissionError(
                f"path {full} escapes repo root {root}"
            ) from exc
        return full


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One-shot return shape. ADR-0003 §ToolResult-shape.

    `content` is what the model sees; `metadata` is for spans / observability;
    `artifacts` will carry screenshots and structured data once browser-use
    lands in S13.
    """

    ok: bool
    content: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """Anything that obeys this Protocol can be registered.

    Sibling implementations live in `tools/native/`, `tools/browser/` (S13),
    `tools/mcp/` (S13). They share NOTHING but this contract.
    """

    name: str
    title: str
    description: str
    args_model: type[BaseModel]
    annotations: ToolAnnotations

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...


def spec_for(tool: Tool) -> ToolSpec:
    """Bridge a Tool to the canonical ToolSpec carried over the wire.

    Adapters consume ToolSpec (not Tool) so they can stay decoupled from the
    M5 package. Pydantic v2 emits JSON Schema; we strip the `title` injected by
    pydantic since the model doesn't need it.
    """
    schema = tool.args_model.model_json_schema()
    schema.pop("title", None)
    return ToolSpec(
        name=tool.name,
        description=tool.description,
        input_schema=schema,
    )
