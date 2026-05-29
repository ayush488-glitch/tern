"""Tests for S20 — StackOverflow lookup (search, store, inject, events)."""
from __future__ import annotations

import typing
from pathlib import Path

import pytest

from tern.lookup.search import SOHit, _strip_html, extract_error_query

# ─── _strip_html ──────────────────────────────────────────────────────────────

def test_strip_html_basic() -> None:
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_entities() -> None:
    result = _strip_html("<p>x &gt; y &amp; z &lt; 1</p>")
    assert ">" in result and "&" in result and "<" in result


def test_strip_html_empty() -> None:
    assert _strip_html("") == ""


# ─── extract_error_query ─────────────────────────────────────────────────────

def test_extract_error_query_picks_error_line() -> None:
    outputs = [
        "some output\nTypeError: unsupported operand type(s) for +: 'int' and 'str'\nmore output",
    ]
    q = extract_error_query(outputs)
    assert "TypeError" in q


def test_extract_error_query_fallback_to_first_line() -> None:
    q = extract_error_query(["just a plain line\nmore stuff"])
    assert q == "just a plain line"


def test_extract_error_query_empty() -> None:
    assert extract_error_query([]) == ""
    assert extract_error_query([""]) == ""


def test_extract_error_query_truncates_at_max_len() -> None:
    q = extract_error_query(["Error: " + "x" * 400], max_len=100)
    assert len(q) <= 100


def test_extract_error_query_prefers_traceback() -> None:
    outputs = ["first line\nTraceback (most recent call last):\n  File blah\nValueError: bad value"]
    q = extract_error_query(outputs)
    assert "Traceback" in q or "ValueError" in q


# ─── SOHit ───────────────────────────────────────────────────────────────────

def test_sohit_frozen() -> None:
    hit = SOHit(
        title="How to fix TypeError",
        link="https://stackoverflow.com/q/1",
        answer_id=42,
        score=10,
        is_answered=True,
        answer_preview="Use str() to convert.",
        tags=("python", "types"),
    )
    with pytest.raises((AttributeError, TypeError)):
        hit.score = 99  # type: ignore[misc]


def test_sohit_defaults() -> None:
    hit = SOHit(title="Q", link="https://so.com/q/2", answer_id=0, score=5, is_answered=False, answer_preview="")
    assert hit.tags == ()


# ─── search() (mocked) ───────────────────────────────────────────────────────

def _fake_search_response() -> object:
    return {
        "items": [
            {
                "title": "How to fix mypy strict error",
                "link": "https://stackoverflow.com/q/123",
                "score": 15,
                "is_answered": True,
                "accepted_answer_id": 456,
                "tags": ["python", "mypy"],
                "answers": [],
            },
            {
                "title": "Another question below min_score",
                "link": "https://stackoverflow.com/q/789",
                "score": 1,
                "is_answered": False,
                "tags": ["python"],
                "answers": [],
            },
        ]
    }


def _fake_answers_response() -> object:
    return {
        "items": [
            {
                "answer_id": 456,
                "body": "<p>Use <code>--strict</code> flag with mypy.</p>",
            }
        ]
    }


def test_search_returns_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    _so_mod = importlib.import_module("tern.lookup.search")
    from tern.lookup.search import search

    call_count = 0

    def fake_get(url: str, params: dict[str, str]) -> object:
        nonlocal call_count
        call_count += 1
        if "search" in url:
            return _fake_search_response()
        return _fake_answers_response()

    monkeypatch.setattr(_so_mod, "_get", fake_get)
    hits = search("mypy strict error", n=3, fetch_bodies=True, _retry=0)
    assert len(hits) == 1  # second item filtered by min_score=2
    assert hits[0].title == "How to fix mypy strict error"
    assert hits[0].answer_id == 456


def test_search_answer_body_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    _so_mod = importlib.import_module("tern.lookup.search")
    from tern.lookup.search import search

    def fake_get(url: str, params: dict[str, str]) -> object:
        if "search" in url:
            return _fake_search_response()
        return _fake_answers_response()

    monkeypatch.setattr(_so_mod, "_get", fake_get)
    hits = search("mypy", n=3, fetch_bodies=True, _retry=0)
    assert "Use" in hits[0].answer_preview
    assert "<p>" not in hits[0].answer_preview


def test_search_no_fetch_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    _so_mod = importlib.import_module("tern.lookup.search")
    from tern.lookup.search import search

    calls: list[str] = []

    def fake_get(url: str, params: dict[str, str]) -> object:
        calls.append(url)
        return _fake_search_response()

    monkeypatch.setattr(_so_mod, "_get", fake_get)
    hits = search("mypy", n=3, fetch_bodies=False, _retry=0)
    assert all("answers" not in u for u in calls)
    assert hits[0].answer_preview == ""


def test_search_network_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    import urllib.error
    _so_mod = importlib.import_module("tern.lookup.search")
    from tern.lookup.search import search

    def fake_get(url: str, params: dict[str, str]) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(_so_mod, "_get", fake_get)
    hits = search("anything", _retry=0)
    assert hits == []


def test_search_caps_at_5(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    _so_mod = importlib.import_module("tern.lookup.search")
    from tern.lookup.search import search

    def fake_get(url: str, params: dict[str, str]) -> object:
        if "search" in url:
            return {
                "items": [
                    {
                        "title": f"Q{i}",
                        "link": f"https://so.com/q/{i}",
                        "score": 10,
                        "is_answered": True,
                        "accepted_answer_id": i,
                        "tags": [],
                        "answers": [],
                    }
                    for i in range(10)
                ]
            }
        return {"items": []}

    monkeypatch.setattr(_so_mod, "_get", fake_get)
    hits = search("q", n=10, fetch_bodies=False, _retry=0)
    assert len(hits) <= 5


# ─── build_so_banner ─────────────────────────────────────────────────────────

def test_build_so_banner_empty() -> None:
    from tern.lookup.inject import build_so_banner

    assert build_so_banner([]) == ""


def test_build_so_banner_structure() -> None:
    from tern.lookup.inject import build_so_banner

    hits = [
        SOHit(
            title="How to fix TypeError",
            link="https://stackoverflow.com/q/1",
            answer_id=10,
            score=12,
            is_answered=True,
            answer_preview="Use int() to convert.",
            tags=("python",),
        ),
    ]
    banner = build_so_banner(hits)
    assert "SIMILAR ERRORS" in banner
    assert "How to fix TypeError" in banner
    assert "score=12" in banner
    assert "answered" in banner
    assert "Use int() to convert." in banner
    assert "python" in banner


def test_build_so_banner_truncates_preview() -> None:
    from tern.lookup.inject import build_so_banner

    long_preview = "x" * 2000
    hits = [SOHit(title="Q", link="https://so.com/q/1", answer_id=1, score=5, is_answered=True, answer_preview=long_preview)]
    banner = build_so_banner(hits)
    # Banner should not contain more than _MAX_PREVIEW chars of the preview
    assert banner.count("x") <= 600


def test_build_so_banner_no_preview() -> None:
    from tern.lookup.inject import build_so_banner

    hits = [SOHit(title="Q", link="https://so.com/q/1", answer_id=0, score=3, is_answered=False, answer_preview="")]
    banner = build_so_banner(hits)
    assert "SIMILAR ERRORS" in banner
    assert "---" not in banner  # no preview section


# ─── SO hit persistence (store.py) ───────────────────────────────────────────

def test_save_and_load_so_hits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    from tern.lookup.store import load_and_clear_so_hits, save_so_hits

    hits = [
        SOHit(title="Q1", link="https://so.com/q/1", answer_id=1, score=9, is_answered=True, answer_preview="ans", tags=("py",)),
        SOHit(title="Q2", link="https://so.com/q/2", answer_id=2, score=7, is_answered=False, answer_preview="", tags=()),
    ]
    save_so_hits(hits)
    loaded = load_and_clear_so_hits()
    assert len(loaded) == 2
    assert loaded[0].title == "Q1"
    assert loaded[1].answer_id == 2
    assert loaded[0].tags == ("py",)


def test_load_so_hits_clears_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    from tern.lookup.store import load_and_clear_so_hits, save_so_hits

    save_so_hits([SOHit(title="Q", link="l", answer_id=1, score=5, is_answered=True, answer_preview="a")])
    load_and_clear_so_hits()
    # second load should return empty (file deleted)
    assert load_and_clear_so_hits() == []


def test_load_so_hits_empty_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    from tern.lookup.store import load_and_clear_so_hits

    assert load_and_clear_so_hits() == []


def test_save_so_hits_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    from tern.lookup.store import load_and_clear_so_hits, save_so_hits

    save_so_hits([])
    loaded = load_and_clear_so_hits()
    assert loaded == []


# ─── SOLookupCompleted event ─────────────────────────────────────────────────

def test_so_lookup_event_defaults() -> None:
    from tern.core.events import SOLookupCompleted

    ev = SOLookupCompleted()
    assert ev.kind == "so_lookup_completed"
    assert ev.n_hits == 0
    assert ev.query == ""


def test_so_lookup_event_in_turn_event_union() -> None:
    from tern.core.events import SOLookupCompleted, TurnEvent

    args = typing.get_args(TurnEvent)
    assert SOLookupCompleted in args


def test_so_lookup_event_frozen() -> None:
    from tern.core.events import SOLookupCompleted

    ev = SOLookupCompleted(query="q", n_hits=2)
    with pytest.raises((AttributeError, TypeError)):
        ev.n_hits = 99  # type: ignore[misc]
