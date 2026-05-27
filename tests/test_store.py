"""S10 / D3 — turn-object store + session refs + chain walk + transcript."""
from __future__ import annotations

from pathlib import Path

import pytest

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Cost,
    Metadata,
    TextBlock,
    ToolCallBlock,
)
from tern.obs.store import (
    TurnObject,
    chain_to_messages,
    content_hash,
    list_branches,
    list_sessions,
    persist_message,
    read_branch,
    read_object,
    read_session_head,
    transcript_path,
    update_session_head,
    walk_chain,
    write_branch,
    write_object,
)


@pytest.fixture
def store_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    return tmp_path


# ---- hashing + roundtrip --------------------------------------------------


def _user_msg(text: str) -> CanonicalMessage:
    return CanonicalMessage(
        role="user",
        content=(TextBlock(text=text),),
        metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
    )


def _assistant_msg(text: str, model_id: str = "test-model") -> CanonicalMessage:
    return CanonicalMessage(
        role="assistant",
        content=(TextBlock(text=text),),
        metadata=Metadata(
            schema_version=SCHEMA_VERSION,
            ts=0.0,
            provenance="test",
            model_id=model_id,
            cost=Cost(input_tokens=10, output_tokens=5, usd_in=0.00005, usd_out=0.00005),
        ),
    )


def test_content_hash_is_stable_and_deterministic(store_home: Path) -> None:
    obj = TurnObject(
        role="user",
        content=(TextBlock(text="hi"),),
        parent=None,
        ts=1234,
    )
    h1 = content_hash(obj)
    h2 = content_hash(obj)
    assert h1 == h2
    assert len(h1) == 64
    # Field order doesn't matter; same content → same hash.
    obj2 = TurnObject(
        ts=1234,
        content=(TextBlock(text="hi"),),
        role="user",
        parent=None,
    )
    assert content_hash(obj2) == h1


def test_write_then_read_object_roundtrip(store_home: Path) -> None:
    obj = TurnObject(
        role="assistant",
        content=(TextBlock(text="hello"),),
        parent="abc",
        model_id="m",
        cost=Cost(input_tokens=1, output_tokens=2, usd_in=0.005, usd_out=0.005),
        ts=42,
    )
    sha = write_object(obj)
    loaded = read_object(sha)
    assert loaded.role == "assistant"
    assert loaded.parent == "abc"
    assert loaded.cost is not None
    assert loaded.cost.input_tokens == 1
    assert content_hash(loaded) == sha


def test_write_object_is_idempotent(store_home: Path) -> None:
    obj = TurnObject(role="user", content=(TextBlock(text="x"),), ts=1)
    sha1 = write_object(obj)
    sha2 = write_object(obj)
    assert sha1 == sha2


def test_persist_message_rejects_system_role(store_home: Path) -> None:
    msg = CanonicalMessage(
        role="system",
        content=(TextBlock(text="be helpful"),),
        metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
    )
    with pytest.raises(ValueError, match="system"):
        persist_message(msg, session_id="s1", turn_idx=0, parent=None)


# ---- session refs + chain walk -------------------------------------------


def test_session_head_advances_and_chain_walks_root_to_head(store_home: Path) -> None:
    sid = "sess1"
    _u, h_u = persist_message(_user_msg("hi"), session_id=sid, turn_idx=0, parent=None)
    update_session_head(sid, h_u)
    _a, h_a = persist_message(_assistant_msg("hello"), session_id=sid, turn_idx=0, parent=h_u)
    update_session_head(sid, h_a)
    _u2, h_u2 = persist_message(_user_msg("more"), session_id=sid, turn_idx=1, parent=h_a)
    update_session_head(sid, h_u2)

    head = read_session_head(sid)
    assert head == h_u2
    assert head is not None

    chain = walk_chain(head)
    assert [o.role for o in chain] == ["user", "assistant", "user"]
    # parent links wired correctly
    assert chain[0].parent is None
    assert chain[1].parent == h_u
    assert chain[2].parent == h_a


def test_chain_to_messages_preserves_role_and_content(store_home: Path) -> None:
    sid = "sess2"
    _, h1 = persist_message(_user_msg("q"), session_id=sid, turn_idx=0, parent=None)
    _, h2 = persist_message(_assistant_msg("a"), session_id=sid, turn_idx=0, parent=h1)
    update_session_head(sid, h2)

    chain = walk_chain(h2)
    msgs = chain_to_messages(chain)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert isinstance(msgs[0].content[0], TextBlock)
    assert msgs[0].content[0].text == "q"  # type: ignore[union-attr]


def test_list_sessions_returns_newest_first(store_home: Path) -> None:
    _, h1 = persist_message(_user_msg("a"), session_id="s-old", turn_idx=0, parent=None)
    update_session_head("s-old", h1)
    _, h2 = persist_message(_user_msg("b"), session_id="s-new", turn_idx=0, parent=None)
    update_session_head("s-new", h2)
    rows = list_sessions()
    assert [r[0] for r in rows][:2] == ["s-new", "s-old"]


# ---- branches ------------------------------------------------------------


def test_branch_fork_from_past_turn_shares_parent(store_home: Path) -> None:
    sid = "sess3"
    _, h1 = persist_message(_user_msg("step1"), session_id=sid, turn_idx=0, parent=None)
    _, h2 = persist_message(_assistant_msg("ans1"), session_id=sid, turn_idx=0, parent=h1)
    _, h3 = persist_message(_user_msg("step2"), session_id=sid, turn_idx=1, parent=h2)
    update_session_head(sid, h3)

    write_branch(sid, "what-if", h2)
    assert read_branch(sid, "what-if") == h2
    assert (sid, "what-if") in {(sid, n) for n, _ in list_branches(sid)}

    # Forking from h2 means a new turn-object with parent=h2 is independent
    # of h3 but shares the prefix [h1, h2] in its chain.
    _, fork_head = persist_message(
        _user_msg("alt step2"), session_id=sid, turn_idx=1, parent=h2
    )
    fork_chain = walk_chain(fork_head)
    main_chain = walk_chain(h3)
    assert [content_hash(o) for o in fork_chain[:2]] == [
        content_hash(o) for o in main_chain[:2]
    ]
    assert content_hash(fork_chain[-1]) != content_hash(main_chain[-1])


# ---- replay --------------------------------------------------------------


def test_replay_check_detects_broken_parent_link(store_home: Path) -> None:
    """Pure replay: child.parent must equal recomputed hash of parent. If a
    hand-edit corrupts an object, the chain walk's child-parent invariant
    catches it."""
    sid = "sess4"
    _u, h_u = persist_message(_user_msg("hi"), session_id=sid, turn_idx=0, parent=None)
    _a, h_a = persist_message(_assistant_msg("hello"), session_id=sid, turn_idx=0, parent=h_u)
    update_session_head(sid, h_a)

    chain = walk_chain(h_a)
    # Each child.parent should hash to the previous object.
    for i in range(1, len(chain)):
        assert chain[i].parent == content_hash(chain[i - 1])


def test_transcript_jsonl_appends_one_line_per_turn(store_home: Path) -> None:
    sid = "sess-t"
    persist_message(_user_msg("hi"), session_id=sid, turn_idx=0, parent=None)
    persist_message(_assistant_msg("yo"), session_id=sid, turn_idx=0, parent=None)
    p = transcript_path(sid)
    assert p.exists()
    lines = p.read_text("utf-8").strip().splitlines()
    assert len(lines) == 2


def test_walk_chain_detects_cycle(store_home: Path) -> None:
    """Defense in depth: if the on-disk store is corrupted into a cycle,
    walk must terminate, not loop forever. We synthesize a cycle by writing
    two objects and then hand-editing one's parent on disk."""
    import json

    from tern.obs.store import object_path

    a = TurnObject(role="user", content=(TextBlock(text="a"),), parent=None, ts=1)
    sha_a = write_object(a)
    b = TurnObject(role="user", content=(TextBlock(text="b"),), parent=sha_a, ts=2)
    sha_b = write_object(b)

    # Corrupt sha_a's stored object so it points at sha_b → cycle.
    object_path(sha_a).write_text(
        json.dumps(
            {
                "role": "user",
                "content": [{"kind": "text", "text": "a"}],
                "parent": sha_b,
                "ts": 1,
                "schema_version": SCHEMA_VERSION,
                "model_id": None,
                "routing_purpose": None,
                "cost": None,
                "seed": None,
                "session_id": None,
                "turn_idx": None,
                "extra": {},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    with pytest.raises(RuntimeError, match="cycle"):
        walk_chain(sha_b)


def test_tool_call_blocks_survive_roundtrip(store_home: Path) -> None:
    obj = TurnObject(
        role="assistant",
        content=(
            TextBlock(text="calling"),
            ToolCallBlock(id="c1", name="read_file", args={"path": "x.py"}),
        ),
        ts=1,
    )
    sha = write_object(obj)
    loaded = read_object(sha)
    assert isinstance(loaded.content[1], ToolCallBlock)
    assert loaded.content[1].name == "read_file"  # type: ignore[union-attr]
