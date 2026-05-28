"""Tests for S18 — KNN recall store (RecallStore, embed shim, banner)."""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import pytest

from tern.recall.embed import _DIM, _ZERO, embed_dim
from tern.recall.store import RecallHit, RecallStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIM_VAL = embed_dim()


def _rand_vec(seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(_DIM_VAL).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()


def _unit_vec(idx: int) -> list[float]:
    """Return a unit vector with 1.0 at position idx and 0 elsewhere."""
    v = [0.0] * _DIM_VAL
    v[idx] = 1.0
    return v


# ---------------------------------------------------------------------------
# embed shim
# ---------------------------------------------------------------------------


def test_embed_dim_constant() -> None:
    assert embed_dim() == 1024


def test_embed_zero_vector_length() -> None:
    assert len(_ZERO) == 1024


# ---------------------------------------------------------------------------
# RecallStore — empty state
# ---------------------------------------------------------------------------


def test_recall_store_empty_size(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    assert store.size == 0


def test_recall_store_empty_query_returns_no_hits(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    hits = store.query(_rand_vec(), top_k=3)
    assert hits == []


def test_recall_store_zero_vec_query_returns_empty(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    store.add("sha1", "prompt", "reply", "code", _rand_vec(0))
    hits = store.query([0.0] * _DIM_VAL)
    assert hits == []


# ---------------------------------------------------------------------------
# RecallStore — add + size
# ---------------------------------------------------------------------------


def test_recall_store_add_increments_size(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    for i in range(5):
        store.add(f"sha{i}", f"prompt {i}", f"reply {i}", "code", _rand_vec(i))
    assert store.size == 5


def test_recall_store_add_wrong_dim_raises(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    with pytest.raises(ValueError, match="vector must be shape"):
        store.add("sha0", "p", "r", "code", [0.1] * 10)


# ---------------------------------------------------------------------------
# RecallStore — query correctness
# ---------------------------------------------------------------------------


def test_recall_store_query_returns_most_similar(tmp_path: Path) -> None:
    """The query vector is identical to turn 2 — that should be the top hit."""
    store = RecallStore(tmp_path)
    vecs = [_rand_vec(i) for i in range(5)]
    for i, v in enumerate(vecs):
        store.add(f"sha{i}", f"prompt {i}", f"reply {i}", "code", v)

    query = vecs[2]  # exact match for turn 2
    hits = store.query(query, top_k=1)
    assert len(hits) == 1
    assert hits[0].sha == "sha2"
    assert hits[0].similarity > 0.99


def test_recall_store_query_top_k_respects_limit(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    for i in range(10):
        store.add(f"sha{i}", f"prompt {i}", f"reply {i}", "code", _rand_vec(i))
    hits = store.query(_rand_vec(0), top_k=3)
    assert len(hits) <= 3


def test_recall_store_query_hits_have_positive_similarity(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    for i in range(5):
        store.add(f"sha{i}", f"prompt {i}", f"reply {i}", "code", _rand_vec(i))
    hits = store.query(_rand_vec(99))
    for hit in hits:
        assert hit.similarity >= 0.0


def test_recall_store_query_orthogonal_vectors_low_sim(tmp_path: Path) -> None:
    """Two fully orthogonal unit vectors should have ~0.0 cosine similarity."""
    v0 = _unit_vec(0)
    v1 = _unit_vec(1)
    store = RecallStore(tmp_path)
    store.add("sha0", "prompt 0", "reply 0", "code", v0)
    hits = store.query(v1, top_k=1)
    # Cosine sim of orthogonal vectors is 0; hit may be returned with sim~0 or dropped.
    if hits:
        assert hits[0].similarity < 0.01


def test_recall_store_query_parallel_vectors_max_sim(tmp_path: Path) -> None:
    """Two identical unit vectors should have cosine similarity ~1.0."""
    v = _unit_vec(0)
    store = RecallStore(tmp_path)
    store.add("sha0", "prompt 0", "reply 0", "arch", v)
    hits = store.query(v, top_k=1)
    assert len(hits) == 1
    assert hits[0].similarity > 0.99


# ---------------------------------------------------------------------------
# RecallStore — persistence (reload between instances)
# ---------------------------------------------------------------------------


def test_recall_store_persists_across_instances(tmp_path: Path) -> None:
    store1 = RecallStore(tmp_path)
    for i in range(3):
        store1.add(f"sha{i}", f"prompt {i}", f"reply {i}", "code", _rand_vec(i))

    # Fresh instance on the same root
    store2 = RecallStore(tmp_path)
    assert store2.size == 3

    hits = store2.query(_rand_vec(0), top_k=1)
    assert len(hits) == 1
    assert hits[0].sha == "sha0"


# ---------------------------------------------------------------------------
# RecallStore — RecallHit fields
# ---------------------------------------------------------------------------


def test_recall_hit_fields_populated(tmp_path: Path) -> None:
    store = RecallStore(tmp_path)
    store.add("abc123", "implement auth", "here is the code", "code", _rand_vec(0))
    hits = store.query(_rand_vec(0), top_k=1)
    assert len(hits) == 1
    h = hits[0]
    assert h.sha == "abc123"
    assert "implement auth" in h.prompt_preview
    assert "here is the code" in h.reply_preview
    assert h.purpose == "code"
    assert isinstance(h.ts, float)
    assert h.ts > 0.0


# ---------------------------------------------------------------------------
# render_recall_banner
# ---------------------------------------------------------------------------


def test_render_recall_banner_empty_returns_empty() -> None:
    from tern.recall.banner import render_recall_banner

    assert render_recall_banner([]) == ""


def test_render_recall_banner_nonempty(tmp_path: Path) -> None:
    from tern.recall.banner import render_recall_banner

    hits = [
        RecallHit(
            sha="abc",
            prompt_preview="implement retry",
            reply_preview="here is the retry code",
            purpose="code",
            similarity=0.87,
            ts=1234567890.0,
        )
    ]
    banner = render_recall_banner(hits)
    assert "SIMILAR PAST TURNS" in banner
    assert "implement retry" in banner
    assert "87%" in banner


# ---------------------------------------------------------------------------
# Banner injection into system prompt
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_recall_banner(tmp_path: Path) -> None:
    """build_system_prompt passes recall_hits through to banner."""
    import os

    os.environ["TERN_HOME"] = str(tmp_path / "tern_home")
    try:
        from tern.recall.store import RecallHit
        from tern.skills.catalog import build_system_prompt

        hits = [
            RecallHit(
                sha="abc",
                prompt_preview="implement retry",
                reply_preview="use exponential backoff",
                purpose="code",
                similarity=0.9,
                ts=1234567890.0,
            )
        ]
        result = build_system_prompt(
            (),
            (),
            include_memory=True,
            cwd=tmp_path,
            recall_hits=hits,  # type: ignore[arg-type]
        )
        assert "SIMILAR PAST TURNS" in result
        assert "implement retry" in result
    finally:
        del os.environ["TERN_HOME"]


def test_build_system_prompt_no_recall_hits_no_banner(tmp_path: Path) -> None:
    import os

    os.environ["TERN_HOME"] = str(tmp_path / "tern_home")
    try:
        from tern.skills.catalog import build_system_prompt

        result = build_system_prompt((), (), include_memory=True, cwd=tmp_path)
        assert "SIMILAR PAST TURNS" not in result
    finally:
        del os.environ["TERN_HOME"]


# ---------------------------------------------------------------------------
# Banner order: MEMORY -> REPO -> RECALL -> USER
# ---------------------------------------------------------------------------


def test_banner_order_with_recall(tmp_path: Path) -> None:
    """Recall banner appears between REPO MEMORY and USER PROFILE."""
    import os

    tern_home = tmp_path / "tern_home"
    os.environ["TERN_HOME"] = str(tern_home)
    try:
        from tern.memory.store import add_entry, render_all_banners_with_repo
        from tern.recall.store import RecallHit

        # Write global memory + user profile
        add_entry("memory", "global note")
        add_entry("user", "user profile entry")

        hits = [
            RecallHit(
                sha="x",
                prompt_preview="old prompt",
                reply_preview="old reply",
                purpose="code",
                similarity=0.85,
                ts=0.0,
            )
        ]
        banner = render_all_banners_with_repo(cwd=tmp_path, recall_hits=hits)  # type: ignore[arg-type]

        mem_pos = banner.find("MEMORY (your personal notes)")
        recall_pos = banner.find("SIMILAR PAST TURNS")
        user_pos = banner.find("USER PROFILE")

        assert mem_pos != -1
        assert recall_pos != -1
        assert user_pos != -1
        assert mem_pos < recall_pos < user_pos
    finally:
        del os.environ["TERN_HOME"]
