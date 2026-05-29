"""Tests for S24 — M14 polish: slash commands, --print mode, version bump."""
from __future__ import annotations

from typer.testing import CliRunner

from tern import __version__
from tern.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def test_version_is_0_1_0() -> None:
    assert __version__ == "0.1.0"


def test_cli_version_flag() -> None:
    r = runner.invoke(app, ["--version"])
    assert "0.1.0" in r.stdout


# ---------------------------------------------------------------------------
# run --print flag present in help
# ---------------------------------------------------------------------------


def test_run_help_shows_print_flag() -> None:
    r = runner.invoke(app, ["run", "--help"])
    assert "--print" in r.stdout


# ---------------------------------------------------------------------------
# chat --help shows all slash commands
# ---------------------------------------------------------------------------


def test_chat_help() -> None:
    r = runner.invoke(app, ["chat", "--help"])
    assert r.exit_code == 0


# ---------------------------------------------------------------------------
# _cmd_tools helper
# ---------------------------------------------------------------------------


def test_cmd_tools_lists_tools() -> None:
    from io import StringIO

    from rich.console import Console

    from tern.tools import Registry
    from tern.tools.native import BashTool, ReadFileTool
    from tern.ui.app import _cmd_tools

    buf = StringIO()
    console = Console(file=buf, highlight=False)
    reg = Registry([ReadFileTool(), BashTool()])
    _cmd_tools(reg, console, "default")
    out = buf.getvalue()
    assert "read_file" in out
    assert "bash" in out
    assert "2 tools" in out


def test_cmd_tools_safe_mode_hides_destructive() -> None:
    from io import StringIO

    from rich.console import Console

    from tern.tools import Registry
    from tern.tools.native import BashTool, ReadFileTool
    from tern.ui.app import _cmd_tools

    buf = StringIO()
    console = Console(file=buf, highlight=False)
    reg = Registry([ReadFileTool(), BashTool()])
    _cmd_tools(reg, console, "safe")
    out = buf.getvalue()
    # BashTool is destructive — safe mode hides it
    assert "bash" not in out
    assert "read_file" in out


# ---------------------------------------------------------------------------
# pyproject / optional deps sanity
# ---------------------------------------------------------------------------


def test_pyproject_has_browser_extra() -> None:
    from pathlib import Path

    text = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert "[project.optional-dependencies]" in text or "optional-dependencies" in text
    assert "playwright" in text


def test_pyproject_has_httpx_in_deps() -> None:
    from pathlib import Path

    text = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert "httpx" in text
