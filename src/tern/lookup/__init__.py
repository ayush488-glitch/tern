"""tern.lookup — StackOverflow error lookup (S20).

Public API::

    from tern.lookup import SOHit, search, fetch_answer_body
    from tern.lookup.inject import build_so_banner

Usage::

    hits = search("mypy strict error: Argument of type str not assignable")
    banner = build_so_banner(hits)
    # inject banner into next turn's system prompt
"""
from tern.lookup.search import SOHit, fetch_answer_body, search

__all__ = ["SOHit", "fetch_answer_body", "search"]
