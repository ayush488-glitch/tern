"""Persistent, non-secret user config at ~/.tern/config.json.

Holds keys like `default_model`. API keys live separately in secrets.py
(different file permissions, different audit story). Both files share the
~/.tern/ root so `TERN_HOME` (or `home` kwarg in tests) redirects them
together.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

_FILENAME: Final = "config.json"

_VALID_KEYS: Final = frozenset({"default_model"})


def _config_path(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home() / ".tern"
    return base / _FILENAME


def _load(home: Path | None = None) -> dict[str, Any]:
    p = _config_path(home)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, Any], home: Path | None = None) -> None:
    p = _config_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def get_config(key: str, default: str | None = None, *, home: Path | None = None) -> str | None:
    val = _load(home).get(key)
    if isinstance(val, str) and val:
        return val
    return default


def set_config(key: str, value: str, *, home: Path | None = None) -> None:
    if key not in _VALID_KEYS:
        raise ValueError(f"unknown config key: {key!r}. valid: {sorted(_VALID_KEYS)}")
    data = _load(home)
    data[key] = value
    _save(data, home)


def list_config(home: Path | None = None) -> dict[str, Any]:
    return dict(_load(home))


def valid_keys() -> tuple[str, ...]:
    return tuple(sorted(_VALID_KEYS))
