"""Span tree → rich.tree.Tree.

Pure rendering. Reads, never writes. Used by `tern spans <session>` and by
tests that want a deterministic str representation.
"""
from __future__ import annotations

from rich.console import Console
from rich.tree import Tree

from tern.obs.span import Span


def _format_duration(ns: int | None) -> str:
    if ns is None:
        return "(open)"
    if ns < 1_000_000:
        return f"{ns/1000:.1f}µs"
    if ns < 1_000_000_000:
        return f"{ns/1_000_000:.1f}ms"
    return f"{ns/1_000_000_000:.2f}s"


def _attach(tree: Tree, span: Span) -> None:
    label = f"[bold]{span.label}[/bold]  [dim]{_format_duration(span.duration_ns)}[/dim]"
    node = tree.add(label)
    for child in span.children:
        _attach(node, child)


def render_forest(roots: list[Span], *, title: str = "spans") -> Tree:
    tree = Tree(f"[bold cyan]{title}[/bold cyan]")
    for root in roots:
        _attach(tree, root)
    return tree


def print_forest(roots: list[Span], *, title: str = "spans", console: Console | None = None) -> None:
    (console or Console()).print(render_forest(roots, title=title))


def forest_to_str(roots: list[Span], *, title: str = "spans") -> str:
    """Plain-text rendering, no ANSI. For tests."""
    console = Console(record=True, force_terminal=False, width=120, color_system=None)
    console.print(render_forest(roots, title=title))
    return console.export_text()
