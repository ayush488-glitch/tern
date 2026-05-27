"""Secret redaction — single regex catalogue applied wherever tool args or
results cross a trust boundary (spans, notes, terminal echo).

Why a module, not inline regex sprinkled per call site:
  - one place to extend (new pattern → coverage everywhere)
  - one place to test (the pattern catalogue is the spec)
  - placeholders are stable per-string so a redacted span is still useful for
    debugging ("API_KEY_0 was used twice")

What this is NOT:
  - DLP. We don't catch every secret shape.
  - encryption. The original strings still live in process memory; redaction
    is a leakage stopgap for things written to disk or displayed.

Apply at sinks (where data leaves the tool boundary), not at sources. Per the
security-engineering skill: redact before block, separate gate, not inline.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Pattern catalogue. Order matters: more specific patterns first so they win
# when prefixes overlap (AWS keys before generic high-entropy).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS_ACCESS_KEY", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bghp_[A-Za-z0-9]{36,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgho_[A-Za-z0-9]{36,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bghs_[A-Za-z0-9]{36,}\b")),
    ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("BEARER_TOKEN", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}\b")),
    ("PRIVATE_KEY_BLOCK", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"
        r"[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"
    )),
    # Loose: kv-style "password=..." / "secret: ..." / "token = ..."
    ("KV_SECRET", re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|"
        r"auth[_-]?token|token)\b\s*[:=]\s*['\"]?([A-Za-z0-9._\-]{12,})['\"]?"
    )),
)


class Redactor:
    """Per-call redactor with a stable placeholder map.

    Same input value → same placeholder within a Redactor's lifetime, so the
    model can still correlate ("the value at line 3 and line 47 are the
    same") without seeing the raw secret.
    """

    def __init__(self) -> None:
        # raw value -> placeholder
        self._map: dict[str, str] = {}
        # category counters
        self._counts: dict[str, int] = {}

    def _placeholder(self, category: str, raw: str) -> str:
        if raw in self._map:
            return self._map[raw]
        idx = self._counts.get(category, 0)
        self._counts[category] = idx + 1
        token = f"<{category}_{idx}>"
        self._map[raw] = token
        return token

    def scrub(self, text: str) -> str:
        """Redact all known patterns in `text`, returning the scrubbed copy."""
        if not text:
            return text
        out = text
        for category, pat in _PATTERNS:
            def _sub(m: re.Match[str], _cat: str = category) -> str:
                # KV_SECRET captures the key name in group(1), the value in (2);
                # we replace only the value so the key stays readable.
                if _cat == "KV_SECRET":
                    raw = m.group(2)
                    return f"{m.group(1)}={self._placeholder(_cat, raw)}"
                raw = m.group(0)
                return self._placeholder(_cat, raw)

            out = pat.sub(_sub, out)
        return out

    def scrub_obj(self, obj: Any) -> Any:
        """Recursively scrub strings inside dicts / lists / tuples."""
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, Mapping):
            return {k: self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            scrubbed = [self.scrub_obj(v) for v in obj]
            return type(obj)(scrubbed) if isinstance(obj, tuple) else scrubbed
        return obj


def scrub(text: str) -> str:
    """One-shot scrub when you don't need a stable placeholder map."""
    return Redactor().scrub(text)


__all__ = ["Redactor", "scrub"]
