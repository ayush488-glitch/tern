"""Tern CLI entry point.

Composition root. Concrete adapters get wired here once they exist; today we
only have the smoke surface (`tern --version`) and the observability surface
(`tern spans <session>`).
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from tern import __version__
from tern.obs.paths import project_dir, spans_path
from tern.obs.render import print_forest
from tern.obs.replay import replay_to_recorder

app = typer.Typer(
    name="tern",
    no_args_is_help=True,
    add_completion=False,
    help="Tern — a Python CLI coding agent.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tern {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Tern — a Python CLI coding agent."""
    return None


@app.command()
def version() -> None:
    """Show version."""
    typer.echo(f"tern {__version__}")


@app.command()
def spans(
    session: str = typer.Argument(..., help="Session id (or partial prefix)."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory (default: current)."),
) -> None:
    """Pretty-print the span tree for a recorded session."""
    path = spans_path(session, cwd=cwd)
    if not path.exists():
        # Try prefix match.
        spans_dir = (project_dir(cwd) / "spans")
        candidates = sorted(spans_dir.glob(f"{session}*.ndjson")) if spans_dir.exists() else []
        if not candidates:
            typer.secho(f"no span file at {path}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        path = candidates[0]
    rec = replay_to_recorder(path)
    title = f"spans · {path.stem}  (cost ${rec.total_cost_usd():.4f})"
    print_forest(rec.roots, title=title, console=Console())


if __name__ == "__main__":
    app()
