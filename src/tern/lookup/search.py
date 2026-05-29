"""StackOverflow search + answer body fetcher (S20).

Uses the public SO API v2.3 — no authentication required for read-only
search. Rate limit is ~300 requests/day without a key (enough for dev use).
With `STACK_APPS_KEY` env var the quota raises to 10k/day.

Endpoints used:
    GET https://api.stackexchange.com/2.3/search/advanced
    GET https://api.stackexchange.com/2.3/answers/{ids}

Both return gzip-compressed JSON. urllib handles the request; html.parser
strips tags from the answer body.
"""
from __future__ import annotations

import gzip
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

_BASE = "https://api.stackexchange.com/2.3"
_SITE = "stackoverflow"
_KEY = os.environ.get("STACK_APPS_KEY", "")  # optional — raises quota when set
_TIMEOUT = 8  # seconds per HTTP call


# ─── data types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class SOHit:
    """One search result from the SO API."""

    title: str
    link: str
    answer_id: int          # 0 if no accepted answer
    score: int
    is_answered: bool
    answer_preview: str     # first 800 chars of accepted/top answer body (plain text)
    tags: tuple[str, ...] = field(default_factory=tuple)


# ─── HTML stripping ───────────────────────────────────────────────────────────

class _StripHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def result(self) -> str:
        return html.unescape(" ".join(self._chunks))


def _strip_html(raw: str) -> str:
    p = _StripHTML()
    p.feed(raw)
    return re.sub(r"\s+", " ", p.result()).strip()


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(url: str, params: dict[str, str]) -> object:
    """GET url?params, return parsed JSON. Raises urllib.error.URLError on failure."""
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={"Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read()
        # SO always gzip-encodes even if we didn't send Accept-Encoding: gzip,
        # so we need to handle both.
        if resp.info().get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw)


# ─── public API ───────────────────────────────────────────────────────────────

def extract_error_query(tool_outputs: list[str], max_len: int = 300) -> str:
    """Pull the most relevant error fragment from tool output strings.

    Strategy:
    1. Lines matching common error patterns (Error:, FAILED, Traceback, etc.)
    2. First such line wins; truncated to max_len.
    3. Fallback: first non-empty output line.
    """
    error_pat = re.compile(
        r"(error:|failed|traceback|exception|typeerror|valueerror|assertionerror|"
        r"importerror|modulenotfounderror|nameerror|attributeerror)",
        re.IGNORECASE,
    )
    for out in tool_outputs:
        for line in out.splitlines():
            line = line.strip()
            if line and error_pat.search(line):
                return line[:max_len]
    # fallback
    for out in tool_outputs:
        line = out.strip().splitlines()[0] if out.strip() else ""
        if line:
            return line[:max_len]
    return ""


def search(
    query: str,
    *,
    n: int = 3,
    tags: str = "python",
    min_score: int = 2,
    fetch_bodies: bool = True,
    _retry: int = 2,
) -> list[SOHit]:
    """Search SO for query, return up to n SOHit objects with answer previews.

    Args:
        query: error message or search string.
        n: max hits to return (capped at 5 to stay within rate limit).
        tags: semicolon-separated tag filter (default: "python").
        min_score: discard questions with score below this threshold.
        fetch_bodies: if True, fetch accepted/top answer body text.
        _retry: internal retry count on transient errors.

    Returns empty list on any network error (never raises).
    """
    n = min(n, 5)
    params: dict[str, str] = {
        "q": query,
        "site": _SITE,
        "order": "desc",
        "sort": "relevance",
        "pagesize": str(n * 3),  # over-fetch to allow score filtering
        "tagged": tags,
        "filter": "withbody",    # include body in question (not answer yet)
    }
    if _KEY:
        params["key"] = _KEY

    data: object = {}
    for attempt in range(_retry + 1):
        try:
            data = _get(f"{_BASE}/search/advanced", params)
            break
        except Exception:
            if attempt == _retry:
                return []
            time.sleep(1.5 ** attempt)

    items: list[object] = []
    if isinstance(data, dict):
        raw_items = data.get("items", [])
        if isinstance(raw_items, list):
            items = raw_items

    hits: list[SOHit] = []
    answer_ids: list[int] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        score = int(item.get("score", 0))
        if score < min_score:
            continue
        accepted_id = int(item.get("accepted_answer_id", 0))
        answers = item.get("answers", [])
        top_id: int = 0
        if isinstance(answers, list) and answers:
            top_id = int(answers[0].get("answer_id", 0))
        aid = accepted_id or top_id
        hits.append(SOHit(
            title=str(item.get("title", "")),
            link=str(item.get("link", "")),
            answer_id=aid,
            score=score,
            is_answered=bool(item.get("is_answered", False)),
            answer_preview="",  # filled below
            tags=tuple(str(t) for t in item.get("tags", [])),
        ))
        if aid:
            answer_ids.append(aid)
        if len(hits) >= n:
            break

    if not fetch_bodies or not answer_ids:
        return hits[:n]

    # Fetch answer bodies in one batch call
    bodies = _fetch_bodies(answer_ids[:5])
    id_to_body: dict[int, str] = {b[0]: b[1] for b in bodies}

    # Rebuild hits with bodies attached
    hits = [
        SOHit(
            title=h.title,
            link=h.link,
            answer_id=h.answer_id,
            score=h.score,
            is_answered=h.is_answered,
            answer_preview=id_to_body.get(h.answer_id, "")[:800],
            tags=h.tags,
        )
        for h in hits
    ]
    return hits[:n]


def fetch_answer_body(answer_id: int) -> str:
    """Fetch plain-text body of a single SO answer. Returns '' on error."""
    results = _fetch_bodies([answer_id])
    return results[0][1] if results else ""


def _fetch_bodies(answer_ids: list[int]) -> list[tuple[int, str]]:
    """Batch-fetch answer bodies. Returns list of (answer_id, plain_text)."""
    if not answer_ids:
        return []
    ids_str = ";".join(str(i) for i in answer_ids)
    params: dict[str, str] = {
        "site": _SITE,
        "filter": "withbody",
        "order": "desc",
        "sort": "votes",
    }
    if _KEY:
        params["key"] = _KEY
    try:
        data = _get(f"{_BASE}/answers/{ids_str}", params)
    except Exception:
        return []
    results: list[tuple[int, str]] = []
    if isinstance(data, dict):
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            aid = int(item.get("answer_id", 0))
            body_html = str(item.get("body", ""))
            results.append((aid, _strip_html(body_html)))
    return results
