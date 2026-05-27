"""API key storage at ~/.tern/secrets.json.

Prompt-on-first-use UX: if a model needs OPENAI_API_KEY and the env var isn't
set, we prompt once via stdin and persist the answer. File is chmod 0600 so
it's at least not world-readable; this is not a vault, it's a convenience
layer over env vars.

Lookup precedence (highest first):
  1. process env (so CI, .envrc, direnv all win)
  2. ~/.tern/secrets.json
  3. interactive stdin prompt (only if `interactive=True`)

Tests pass `home=tmp_path` to redirect storage.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Final

_FILENAME: Final = "secrets.json"


def _secrets_path(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home() / ".tern"
    return base / _FILENAME


def _load(home: Path | None = None) -> dict[str, str]:
    p = _secrets_path(home)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _save(data: dict[str, str], home: Path | None = None) -> None:
    p = _secrets_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)


def get_secret(
    name: str,
    *,
    home: Path | None = None,
    interactive: bool = False,
    prompt: str | None = None,
) -> str | None:
    """Resolve a secret by name. Returns None if not found and not interactive."""
    val = os.environ.get(name)
    if val:
        return val
    data = _load(home)
    if data.get(name):
        return data[name]
    if interactive and sys.stdin.isatty():
        msg = prompt or f"{name} is not set. Paste it now (will be saved to {_secrets_path(home)}): "
        try:
            entered = input(msg).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if entered:
            data[name] = entered
            _save(data, home)
            return entered
    return None


def set_secret(name: str, value: str, *, home: Path | None = None) -> None:
    data = _load(home)
    data[name] = value
    _save(data, home)


def list_secret_names(home: Path | None = None) -> tuple[str, ...]:
    """Return sorted names (no values) — for `tern config show`."""
    return tuple(sorted(_load(home).keys()))
