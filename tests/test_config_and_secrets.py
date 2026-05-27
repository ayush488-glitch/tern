"""Tests for ~/.tern/secrets.json + config.json — env precedence, persistence, redirects."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tern.core import config as tcfg
from tern.core import secrets as tsec


def test_secret_env_wins_over_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tsec.set_secret("OPENAI_API_KEY", "from-file", home=tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert tsec.get_secret("OPENAI_API_KEY", home=tmp_path) == "from-env"


def test_secret_file_used_when_env_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tsec.set_secret("OPENAI_API_KEY", "stored-key", home=tmp_path)
    assert tsec.get_secret("OPENAI_API_KEY", home=tmp_path) == "stored-key"


def test_secret_returns_none_when_missing_and_non_interactive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_KEY", raising=False)
    assert tsec.get_secret("MISSING_KEY", home=tmp_path, interactive=False) is None


def test_secret_file_perms_locked_down(tmp_path: Path) -> None:
    tsec.set_secret("X", "y", home=tmp_path)
    p = tmp_path / "secrets.json"
    assert p.exists()
    # On macOS / Linux the chmod 0600 should hold.
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600


def test_list_secret_names_returns_keys_only(tmp_path: Path) -> None:
    tsec.set_secret("A", "1", home=tmp_path)
    tsec.set_secret("B", "2", home=tmp_path)
    assert tsec.list_secret_names(tmp_path) == ("A", "B")


def test_secret_file_corruption_returns_empty(tmp_path: Path) -> None:
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets.json").write_text("not json", encoding="utf-8")
    assert tsec.get_secret("ANY", home=tmp_path) is None


def test_config_set_unknown_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        tcfg.set_config("nope", "x", home=tmp_path)


def test_config_default_model_roundtrip(tmp_path: Path) -> None:
    tcfg.set_config("default_model", "gpt-5-mini", home=tmp_path)
    assert tcfg.get_config("default_model", home=tmp_path) == "gpt-5-mini"


def test_config_get_default_when_missing(tmp_path: Path) -> None:
    assert tcfg.get_config("default_model", home=tmp_path) is None
    assert tcfg.get_config("default_model", default="x", home=tmp_path) == "x"


def test_config_show_round_trip(tmp_path: Path) -> None:
    tcfg.set_config("default_model", "us.amazon.nova-lite-v1:0", home=tmp_path)
    assert tcfg.list_config(tmp_path) == {"default_model": "us.amazon.nova-lite-v1:0"}
    # File is plain json (non-secret)
    p = tmp_path / "config.json"
    assert json.loads(p.read_text()) == {"default_model": "us.amazon.nova-lite-v1:0"}


def test_secret_env_dropped_then_file_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO", "env-val")
    assert tsec.get_secret("FOO", home=tmp_path) == "env-val"
    monkeypatch.delenv("FOO")
    tsec.set_secret("FOO", "file-val", home=tmp_path)
    assert tsec.get_secret("FOO", home=tmp_path) == "file-val"
    # The home parameter is what redirects, not env, so HOME unchanged is fine
    _ = os  # silence unused-import warning in some environments
