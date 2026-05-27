"""M11 — observability.

Span recorder, NDJSON sink, span-tree renderer. Consumes the TurnEvent stream
defined in tern.core.events; produces append-only span logs at
~/.tern/projects/<sanitized-cwd>/spans/<session_id>.ndjson and a rich-rendered
tree for `tern spans <session>`.

ADR refs:
- wiki/decisions/adr-0002-runtime-shape.md (event vocabulary)
- wiki/decisions/adr-0005-session-state.md (storage layout)
"""
