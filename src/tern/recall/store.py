"""RecallStore — per-repo KNN index over assistant turn spans (ADR-0011 §2).

Storage layout (all under project_root/.tern/recall/):
    vectors.npy         float32 array of shape (N, 1024)
    metadata.jsonl      one JSON line per row: {sha, prompt_preview, reply_preview, purpose, ts}

On first use the directory + files are created automatically.

KNN is cosine similarity (brute-force, fine for N < 50 000 on one repo).
numpy is required (added to pyproject.toml in S18).
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tern.recall.embed import embed_dim

_VECTOR_FILE = "vectors.npy"
_META_FILE = "metadata.jsonl"
_DEFAULT_TOP_K = 3


@dataclass(frozen=True, slots=True)
class RecallHit:
    sha: str
    prompt_preview: str
    reply_preview: str
    purpose: str
    similarity: float
    ts: float


class RecallStore:
    """Per-repo recall index.

    Usage:
        store = RecallStore(repo_root)
        store.add(sha, prompt, reply, purpose, vec)  # after a successful turn
        hits = store.query(new_prompt_vec, top_k=3)
    """

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root / ".tern" / "recall"
        self._vec_path = self._root / _VECTOR_FILE
        self._meta_path = self._root / _META_FILE
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Number of indexed turns."""
        if not self._meta_path.exists():
            return 0
        return sum(1 for _ in self._meta_path.open("r", encoding="utf-8"))

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(
        self,
        sha: str,
        prompt: str,
        reply: str,
        purpose: str,
        vector: list[float],
    ) -> None:
        """Append one turn to the index. Atomic append for both files."""
        dim = embed_dim()
        vec = np.array(vector, dtype=np.float32)
        if vec.shape != (dim,):
            raise ValueError(f"vector must be shape ({dim},), got {vec.shape}")

        # Vectors: load existing, append, atomic write.
        existing = self._load_vectors()
        if existing is None:
            new_arr = vec[np.newaxis, :]  # (1, dim)
        else:
            new_arr = np.vstack([existing, vec[np.newaxis, :]])  # (N+1, dim)
        self._save_vectors(new_arr)

        # Metadata: atomic append.
        row = json.dumps({
            "sha": sha,
            "prompt_preview": prompt[:200],
            "reply_preview": reply[:200],
            "purpose": purpose,
            "ts": time.time(),
        })
        self._atomic_append_line(self._meta_path, row)

    # ------------------------------------------------------------------
    # Read / Query
    # ------------------------------------------------------------------

    def query(
        self,
        query_vector: list[float],
        top_k: int = _DEFAULT_TOP_K,
    ) -> list[RecallHit]:
        """Return up to top_k most similar past turns by cosine similarity.

        Zero-vectors (embed failures) are silently skipped.
        Returns empty list when index is empty or query is zero-vector.
        """
        vectors = self._load_vectors()
        if vectors is None or vectors.shape[0] == 0:
            return []

        qvec = np.array(query_vector, dtype=np.float32)
        if np.allclose(qvec, 0.0):
            return []

        # Cosine similarity: dot product on normalised vectors.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Zero-vectors in the store get norm 0; mask them out.
        safe = norms[:, 0] > 1e-9
        if not safe.any():
            return []

        qnorm = np.linalg.norm(qvec)
        if qnorm < 1e-9:
            return []

        similarities = (vectors @ qvec) / (norms[:, 0] * qnorm + 1e-9)
        similarities = np.where(safe, similarities, -2.0)

        meta = self._load_meta()
        if not meta:
            return []

        n = min(len(meta), vectors.shape[0])
        similarities = similarities[:n]
        top_idx = np.argsort(-similarities)[:top_k]

        hits: list[RecallHit] = []
        for idx in top_idx:
            row = meta[int(idx)]
            sim = float(similarities[int(idx)])
            if sim < 0.0:
                continue
            hits.append(
                RecallHit(
                    sha=row.get("sha", ""),  # type: ignore[arg-type]
                    prompt_preview=row.get("prompt_preview", ""),  # type: ignore[arg-type]
                    reply_preview=row.get("reply_preview", ""),  # type: ignore[arg-type]
                    purpose=row.get("purpose", ""),  # type: ignore[arg-type]
                    similarity=sim,
                    ts=float(row.get("ts", 0.0)),  # type: ignore[arg-type]
                )
            )
        return hits

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_vectors(self) -> np.ndarray | None:  # type: ignore[type-arg]
        if not self._vec_path.exists():
            return None
        try:
            arr = np.load(str(self._vec_path))
            return arr if arr.ndim == 2 else None
        except Exception:
            return None

    def _save_vectors(self, arr: np.ndarray) -> None:  # type: ignore[type-arg]
        fd, tmp = tempfile.mkstemp(dir=self._root, suffix=".npy")
        try:
            os.close(fd)
            np.save(tmp, arr)
            os.replace(tmp, self._vec_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _load_meta(self) -> list[dict[str, object]]:
        if not self._meta_path.exists():
            return []
        rows: list[dict[str, object]] = []
        try:
            for line in self._meta_path.open("r", encoding="utf-8"):
                stripped = line.strip()
                if stripped:
                    rows.append(json.loads(stripped))
        except Exception:
            pass
        return rows

    def _atomic_append_line(self, path: Path, line: str) -> None:
        """Append one line atomically via tmp-file rename on the same filesystem."""
        existing = path.read_bytes() if path.exists() else b""
        new_content = existing + (line + "\n").encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=self._root, suffix=".jsonl")
        try:
            os.close(fd)
            Path(tmp).write_bytes(new_content)
            os.replace(tmp, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
