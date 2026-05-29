"""tern.loop — intra-turn hardening primitives (S21 / ADR-0012).

Modules:
  summarize  — working-set summarizer (intra-turn pressure relief)
  delegate   — sub-turn delegation (child context isolation)
  read_cache — content-addressed read cache (repeat-read token savings)
  budget     — session + per-turn cost budget enforcement
"""
