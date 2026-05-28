"""Tern recall package — per-repo KNN similarity recall (ADR-0011 subsystem 2).

Public surface:
    RecallStore         — index on disk; embed + query
    render_recall_banner(hits) -> str
"""
from tern.recall.banner import render_recall_banner
from tern.recall.store import RecallHit, RecallStore

__all__ = ["RecallHit", "RecallStore", "render_recall_banner"]
