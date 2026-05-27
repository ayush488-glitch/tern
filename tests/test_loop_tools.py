"""Loop tests for M5 wiring: tool execution, reflection, permission, multi-step."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Capabilities,
    Cost,
    Metadata,
    ProviderResponse,
    TextBlock,
    ToolCallBlock,
    ToolSpec,
)
from tern.core.events import (
    ApprovalDenied,
    ApprovalGranted,
    ApprovalRequested,
    ReflectionTriggered,
    ToolCalled,
    ToolReturned,
    TurnCompleted,
)
from tern.core.loop import run_turn
from tern.core.turn import Turn, TurnPurpose
from tern.tools import (
    ApprovalDecision,
    PermissionGate,
    Registry,
)
from tern.tools.native import EditBlockTool, ReadFileTool
from tests.tools._fakes import FakeDestructiveTool, FakeReadOnlyTool

# ---- scripted adapter -----------------------------------------------------


class ScriptedAdapter:
    """Returns a queue of pre-canned ProviderResponses, one per call.

    Each step's response can be:
      - a list of (tool_name, args_dict) tuples → assistant emits tool_use blocks
      - a string → assistant emits a single text block (final answer)
    """

    name = "scripted"
    model_id = "scripted-model"
    capabilities = Capabilities(tool_use=True, vision=False)

    def __init__(self, script: Sequence[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> ProviderResponse:
        self.calls.append({"n_messages": len(messages), "n_tools": len(tools)})
        step = self._script.pop(0)
        cost = Cost(input_tokens=5, output_tokens=2, usd_in=0.0, usd_out=0.0)

        if isinstance(step, str):
            blocks: tuple[Any, ...] = (TextBlock(text=step),)
            stop_reason = "end_turn"
        else:
            blocks = tuple(
                ToolCallBlock(id=f"call_{i}", name=name, args=dict(args))
                for i, (name, args) in enumerate(step)
            )
            stop_reason = "tool_use"

        msg = CanonicalMessage(
            role="assistant",
            content=blocks,
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=0.0,
                model_id=self.model_id,
                cost=cost,
                provenance="scripted",
            ),
        )
        return ProviderResponse(
            message=msg, stop_reason=stop_reason, cost=cost, raw_id="rid"
        )

    @staticmethod
    def to_wire(
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        return {}

    @staticmethod
    def from_wire(response: Any) -> ProviderResponse:  # pragma: no cover
        raise NotImplementedError


def _turn(
    *,
    registry: Registry | None = None,
    gate: PermissionGate | None = None,
    repo_root: Path,
    mode: str = "default",
    max_steps: int = 5,
) -> Turn:
    return Turn(
        id="t",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(
            CanonicalMessage(
                role="user",
                content=(TextBlock(text="please"),),
                metadata=Metadata(
                    schema_version=SCHEMA_VERSION, ts=0.0, provenance="cli"
                ),
            ),
        ),
        registry=registry,
        gate=gate,
        mode=mode,
        repo_root=repo_root,
        max_steps=max_steps,
    )


# ---- tests ----------------------------------------------------------------


async def test_loop_executes_read_then_finishes(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("alpha\n")
    adapter = ScriptedAdapter(
        [
            [("read_file", {"path": "x.txt"})],
            "the file says alpha",
        ]
    )
    turn = _turn(
        registry=Registry([ReadFileTool()]),
        gate=PermissionGate(),
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]

    called = [e for e in events if isinstance(e, ToolCalled)]
    returned = [e for e in events if isinstance(e, ToolReturned)]
    assert len(called) == 1 and called[0].tool_name == "read_file"
    assert len(returned) == 1 and returned[0].ok
    completed = [e for e in events if isinstance(e, TurnCompleted)]
    assert completed and completed[0].reason == "done"
    # No approval events for read-only.
    assert not any(isinstance(e, ApprovalRequested) for e in events)


async def test_loop_destructive_emits_approval_pair(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("def f():\n    return 1\n")

    async def grant(*_: Any) -> ApprovalDecision:
        return ApprovalDecision.GRANTED

    adapter = ScriptedAdapter(
        [
            [("edit_block", {"path": "f.py", "search": "return 1", "replace": "return 2"})],
            "edited",
        ]
    )
    turn = _turn(
        registry=Registry([EditBlockTool()]),
        gate=PermissionGate(prompter=grant),
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    assert any(isinstance(e, ApprovalRequested) for e in events)
    assert any(isinstance(e, ApprovalGranted) for e in events)
    assert f.read_text() == "def f():\n    return 2\n"


async def test_loop_destructive_denied_closes_turn(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("x = 1\n")

    async def deny(*_: Any) -> ApprovalDecision:
        return ApprovalDecision.DENIED

    adapter = ScriptedAdapter(
        [[("edit_block", {"path": "f.py", "search": "x = 1", "replace": "x = 2"})]]
    )
    turn = _turn(
        registry=Registry([EditBlockTool()]),
        gate=PermissionGate(prompter=deny),
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    assert any(isinstance(e, ApprovalDenied) for e in events)
    completed = [e for e in events if isinstance(e, TurnCompleted)]
    assert completed and completed[0].reason == "permission_denied"
    assert f.read_text() == "x = 1\n"  # unchanged


async def test_loop_invalid_args_triggers_reflection(tmp_path: Path) -> None:
    """Bad args → ReflectionTriggered event + tool_result(ok=False) → next step continues."""
    f = tmp_path / "x.txt"
    f.write_text("hi\n")
    adapter = ScriptedAdapter(
        [
            # Step 1: model passes a wrong field name; pydantic rejects.
            [("read_file", {"wrong_field": "x.txt"})],
            # Step 2: model corrects and reads the file.
            [("read_file", {"path": "x.txt"})],
            "ok",
        ]
    )
    turn = _turn(
        registry=Registry([ReadFileTool()]),
        gate=PermissionGate(),
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    refl = [e for e in events if isinstance(e, ReflectionTriggered)]
    assert refl and refl[0].cause == "validation_error"
    # Two LLM round-trips happened.
    assert len(adapter.calls) == 3


async def test_loop_unknown_tool_triggers_reflection(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            [("does_not_exist", {})],
            "fine",
        ]
    )
    turn = _turn(
        registry=Registry([ReadFileTool()]),
        gate=PermissionGate(),
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    refl = [e for e in events if isinstance(e, ReflectionTriggered)]
    assert refl and refl[0].cause.startswith("unknown_tool:")


async def test_loop_max_steps_caps_runaway(tmp_path: Path) -> None:
    # Adapter never stops calling read_file.
    adapter = ScriptedAdapter([[("read_file", {"path": "x.txt"})]] * 5)
    (tmp_path / "x.txt").write_text("hi\n")
    turn = _turn(
        registry=Registry([ReadFileTool()]),
        gate=PermissionGate(),
        repo_root=tmp_path,
        max_steps=3,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    completed = [e for e in events if isinstance(e, TurnCompleted)]
    assert completed and completed[0].reason == "max_steps"
    assert len(adapter.calls) == 3


async def test_loop_safe_mode_drops_destructive_from_specs(tmp_path: Path) -> None:
    """In safe mode the destructive tool is filtered before the model sees it."""
    seen_specs: list[int] = []

    class Recorder(ScriptedAdapter):
        async def complete(self, *args: Any, **kwargs: Any) -> ProviderResponse:
            seen_specs.append(len(kwargs["tools"]))
            return await super().complete(*args, **kwargs)

    adapter = Recorder(["just text"])
    turn = _turn(
        registry=Registry([ReadFileTool(), EditBlockTool()]),
        gate=PermissionGate(),
        repo_root=tmp_path,
        mode="safe",
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    assert seen_specs == [1]  # only read_file visible
    assert any(isinstance(e, TurnCompleted) for e in events)


async def test_loop_with_no_registry_runs_textonly_legacy(tmp_path: Path) -> None:
    """S8 callers (no registry / no gate) still work — turn finishes on first text."""
    adapter = ScriptedAdapter(["hello world"])
    turn = _turn(repo_root=tmp_path)  # no registry, no gate
    events = [ev async for ev in run_turn(turn, adapter)]
    completed = [e for e in events if isinstance(e, TurnCompleted)]
    assert completed and completed[0].reason == "done"


async def test_loop_destructive_silently_blocked_no_prompter_continues(tmp_path: Path) -> None:
    """If a destructive tool is in default mode but no prompter wired, gate
    raises ToolBlocked; loop should NOT close (it's a tool-level failure, not a
    user denial), feeding the error back so the model can react."""
    f = tmp_path / "f.py"
    f.write_text("x = 1\n")
    adapter = ScriptedAdapter(
        [
            [("fake_write", {"payload": "boom"})],
            "ack",
        ]
    )
    turn = _turn(
        registry=Registry([FakeReadOnlyTool(), FakeDestructiveTool()]),
        gate=PermissionGate(),  # no prompter
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    completed = [e for e in events if isinstance(e, TurnCompleted)]
    assert completed and completed[0].reason == "done"
    # ApprovalDenied was emitted (gate rejected before invoke).
    assert any(isinstance(e, ApprovalDenied) for e in events)


async def test_args_preview_truncates_long_payloads(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hi\n")
    adapter = ScriptedAdapter(
        [
            [("read_file", {"path": "x.txt", "offset": 1, "limit": 1})],
            "ok",
        ]
    )
    turn = _turn(
        registry=Registry([ReadFileTool()]),
        gate=PermissionGate(),
        repo_root=tmp_path,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    called = [e for e in events if isinstance(e, ToolCalled)]
    assert called and len(called[0].args_preview) <= 80
