"""Tests for Bedrock retry/backoff (S14 / M12)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from botocore.exceptions import ClientError

from tern.adapters import bedrock_anthropic as ba
from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeClient:
    """Records calls and replays a script of (exception | response)."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls = 0

    def invoke_model(self, **_kw: Any) -> dict[str, Any]:
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return {"body": _FakeBody(item)}


def _throttle() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
        "InvokeModel",
    )


def _validation() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ValidationException", "Message": "bad input"}},
        "InvokeModel",
    )


def _ok_payload() -> bytes:
    import json

    return json.dumps({
        "id": "id1",
        "model": "test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode("utf-8")


def test_retries_on_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_throttle(), _throttle(), _ok_payload()])
    monkeypatch.setattr(ba.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ba, "_sleep_with_jitter", lambda _attempt: _noop_async())

    adapter = BedrockAnthropicAdapter(model_id="test")
    resp = asyncio.run(adapter.complete((), (), max_tokens=10))
    assert resp.stop_reason == "end_turn"
    assert fake.calls == 3


def test_does_not_retry_on_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_validation()])
    monkeypatch.setattr(ba.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ba, "_sleep_with_jitter", lambda _attempt: _noop_async())

    adapter = BedrockAnthropicAdapter(model_id="test")
    with pytest.raises(ClientError):
        asyncio.run(adapter.complete((), (), max_tokens=10))
    assert fake.calls == 1


def test_gives_up_after_max(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_throttle()] * 10)
    monkeypatch.setattr(ba.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ba, "_sleep_with_jitter", lambda _attempt: _noop_async())

    adapter = BedrockAnthropicAdapter(model_id="test")
    with pytest.raises(ClientError):
        asyncio.run(adapter.complete((), (), max_tokens=10))
    # _MAX_RETRIES + 1 attempts
    assert fake.calls == ba._MAX_RETRIES + 1


async def _noop_async() -> None:
    return None
