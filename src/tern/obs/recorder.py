"""Recorder — turns an event stream into a Span forest.

State machine:
    open events     → push a Span onto the open-stack (under current top as parent)
    close events    → pop the matching opener, attach as `closer`, seal
    singletons      → attach as a child of current top, no Span pairing

If the stream ends with open spans, they stay open; renderer marks them as
in-flight. We never pretend a missing closer arrived.
"""
from __future__ import annotations

from tern.core.events import TurnEvent, opener_kind_for
from tern.obs.sink import NDJSONSpanSink
from tern.obs.span import Span


class SpanRecorder:
    """Consume events, maintain a span tree, optionally write to a sink.

    Usage:
        rec = SpanRecorder(sink=NDJSONSpanSink(session_id="abc"))
        async for ev in run_turn(...):
            rec.consume(ev)
        tree = rec.roots
    """

    def __init__(self, *, sink: NDJSONSpanSink | None = None) -> None:
        self.sink = sink
        self.roots: list[Span] = []
        self._open_stack: list[Span] = []
        # Index opened spans by id so closers find them in O(1).
        self._by_id: dict[str, Span] = {}

    @property
    def current(self) -> Span | None:
        return self._open_stack[-1] if self._open_stack else None

    def consume(self, ev: TurnEvent) -> None:
        if self.sink is not None:
            self.sink.write(ev)

        kind = ev.kind
        closer_for = opener_kind_for(kind)

        if closer_for is not None:
            # Closer event — find its opener and seal.
            self._close(ev, closer_for)
            return

        # Either an opener or a singleton. Heuristic: we recognize openers by
        # being explicitly listed as values in events._OPENERS. Anything else
        # is a singleton attached to current top (or a root if stack empty).
        if self._is_opener(kind):
            span = Span(
                id=ev.id,
                parent_id=self.current.id if self.current else None,
                kind=kind,
                opener=ev,
            )
            self._by_id[span.id] = span
            if self.current is not None:
                self.current.children.append(span)
            else:
                self.roots.append(span)
            self._open_stack.append(span)
        else:
            # Singleton — wrap in a closed span (opener==closer) so the tree
            # shows it. Cheap and uniform.
            singleton = Span(
                id=ev.id,
                parent_id=self.current.id if self.current else None,
                kind=kind,
                opener=ev,
                closer=ev,
            )
            if self.current is not None:
                self.current.children.append(singleton)
            else:
                self.roots.append(singleton)

    @staticmethod
    def _is_opener(kind: str) -> bool:
        from tern.core.events import _OPENERS
        return kind in _OPENERS.values() or kind == "turn_started"

    def _close(self, ev: TurnEvent, opener_kind: str) -> None:
        # Walk the open stack from top to bottom looking for the matching opener.
        # Match is by call_id when present (tools, approvals); otherwise by kind.
        match_attr = None
        for attr in ("call_id",):
            if hasattr(ev, attr):
                match_attr = attr
                break

        for i in range(len(self._open_stack) - 1, -1, -1):
            sp = self._open_stack[i]
            if sp.kind != opener_kind:
                continue
            if match_attr is not None:
                op_val = getattr(sp.opener, match_attr, None)
                cl_val = getattr(ev, match_attr, None)
                if op_val and cl_val and op_val != cl_val:
                    continue
            # Found it — seal, pop everything above it.
            sp.closer = ev
            del self._open_stack[i:]
            return
        # No match. Drop it; recorder is best-effort. (Could log a warning;
        # we don't want noise in tests.)
        return

    def total_cost_usd(self) -> float:
        return sum(r.total_cost_usd() for r in self.roots)
