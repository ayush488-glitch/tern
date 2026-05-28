"""Tern router package — per-turn cognitive routing (ADR-0011 subsystem 1).

Public surface:
    classify(prompt, mode) -> tuple[TurnPurpose, str]
    route(prompt, mode) -> tuple[TurnPurpose, str, str]
"""
from tern.router.classify import classify
from tern.router.route import route

__all__ = ["classify", "route"]
