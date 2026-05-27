"""Smoke tests — the green floor.

If these fail, nothing else can be trusted. Keep tiny.
"""

from __future__ import annotations

from typer.testing import CliRunner

from tern import __version__
from tern.cli import app

runner = CliRunner()


def test_version_constant() -> None:
    assert __version__ == "0.0.1"


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "tern 0.0.1" in result.stdout


def test_cli_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "tern 0.0.1" in result.stdout
