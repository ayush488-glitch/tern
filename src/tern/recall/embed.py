"""Bedrock Titan Text Embeddings V2 — lightweight wrapper.

One public function: embed(text) -> list[float] (1024-dim).

On any Bedrock error returns a zero vector so a bad embed never kills a turn.
The store skips zero-vectors when computing cosine similarity, so the miss is
silent.
"""
from __future__ import annotations

import json
import logging

_DIM = 1024
_ZERO: list[float] = [0.0] * _DIM
_MODEL_ID = "amazon.titan-embed-text-v2:0"

log = logging.getLogger(__name__)


def embed(text: str, *, region: str = "us-east-1") -> list[float]:
    """Return a 1024-dim embedding vector from Bedrock Titan v2.

    Falls back to zero-vector on any error (network, throttle, parse).
    """
    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=region)
        body = json.dumps({"inputText": text[:8192], "dimensions": _DIM, "normalize": True})
        result = client.invoke_model(
            modelId=_MODEL_ID,
            body=body.encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        decoded = json.loads(result["body"].read().decode("utf-8"))
        vec: list[float] = decoded.get("embedding", _ZERO)
        return vec if len(vec) == _DIM else _ZERO
    except Exception as exc:
        log.debug("embed failed, using zero vector: %s", exc)
        return list(_ZERO)


def embed_dim() -> int:
    return _DIM
