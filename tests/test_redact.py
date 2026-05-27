"""Tests for the secret redactor (S14 / ADR-0010)."""

from __future__ import annotations

from tern.obs.redact import Redactor, scrub


def test_aws_access_key() -> None:
    txt = "creds: AKIAIOSFODNN7EXAMPLE rest"
    out = scrub(txt)
    assert "AKIA" not in out
    assert "<AWS_ACCESS_KEY_0>" in out


def test_github_token() -> None:
    txt = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    out = scrub(txt)
    assert "ghp_" not in out
    assert "<GITHUB_TOKEN_0>" in out


def test_openai_key() -> None:
    txt = "key=sk-abcdefghijklmnopqrstuv"
    out = scrub(txt)
    assert "sk-abc" not in out


def test_bearer_token() -> None:
    txt = "Authorization: Bearer abcdefghijklmnopqrstuv1234"
    out = scrub(txt)
    assert "abcdefghij" not in out


def test_kv_password() -> None:
    txt = 'password="hunter2hunter2hunter2"'
    out = scrub(txt)
    assert "hunter2" not in out
    assert "password=" in out  # key preserved


def test_private_key_block() -> None:
    txt = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890abcdef\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = scrub(txt)
    assert "MIIEpAIB" not in out
    assert "PRIVATE_KEY_BLOCK" in out


def test_stable_placeholders() -> None:
    r = Redactor()
    a = r.scrub("AKIAIOSFODNN7EXAMPLE")
    b = r.scrub("AKIAIOSFODNN7EXAMPLE again")
    # same raw value -> same placeholder across calls
    assert "<AWS_ACCESS_KEY_0>" in a
    assert "<AWS_ACCESS_KEY_0>" in b


def test_distinct_secrets_get_distinct_placeholders() -> None:
    r = Redactor()
    out = r.scrub("AKIAIOSFODNN7EXAMPLE AKIAZZZZZZZZZZZZZZZZ")
    assert "<AWS_ACCESS_KEY_0>" in out
    assert "<AWS_ACCESS_KEY_1>" in out


def test_scrub_obj_recursive() -> None:
    r = Redactor()
    obj = {
        "args": {"command": "use AKIAIOSFODNN7EXAMPLE here"},
        "list": ["ghp_abcdefghijklmnopqrstuvwxyz0123456789", 42],
    }
    out = r.scrub_obj(obj)
    assert "AKIA" not in str(out)
    assert "ghp_" not in str(out)
    assert out["list"][1] == 42  # non-strings untouched


def test_passthrough_when_no_secrets() -> None:
    txt = "just some normal log line"
    assert scrub(txt) == txt
