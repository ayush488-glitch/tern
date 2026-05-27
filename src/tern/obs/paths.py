"""Path resolution for ~/.tern/.

Centralized so tests can override TERN_HOME and so ADR-0005's storage layout
has exactly one source of truth.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def tern_home() -> Path:
    """Root of Tern's local state. Override with TERN_HOME env var."""
    override = os.environ.get("TERN_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".tern"


def sanitize_cwd(cwd: Path | None = None) -> str:
    """Convert a working-directory path to a safe single-segment dir name.

    Mirrors claude-code's `<sanitized-cwd>` scheme — replace path separators
    and unsafe chars with hyphens; leading hyphen kept off.
    """
    p = (cwd or Path.cwd()).resolve()
    raw = str(p)
    s = re.sub(r"[^A-Za-z0-9_.-]", "-", raw)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "root"


def project_dir(cwd: Path | None = None) -> Path:
    """~/.tern/projects/<sanitized-cwd>/ — created on demand."""
    d = tern_home() / "projects" / sanitize_cwd(cwd)
    d.mkdir(parents=True, exist_ok=True)
    return d


def spans_path(session_id: str, cwd: Path | None = None) -> Path:
    d = project_dir(cwd) / "spans"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.ndjson"
