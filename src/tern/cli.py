"""Tern CLI entry point.

This is the composition root — the only place that imports concrete adapters
once the agent core lands. Today it's just a smoke surface for `tern --version`.
"""

from __future__ import annotations

import typer
from rich.console import Console

from tern import __version__

app = typer.Typer(
    name="tern",
    help="A Python CLI coding agent.",
    add_completion=False,
)

_console = Console()


@app.command()
def version() -> None:
    """Print the Tern version."""
    _console.print(f"tern {__version__}")


def _version_callback(value: bool) -> None:
    if value:
        _console.print(f"tern {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    show_version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        _console.print(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
