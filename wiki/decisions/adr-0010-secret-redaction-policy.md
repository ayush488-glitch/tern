---
title: ADR-0010 — secret redaction policy
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [security, redaction, observability, s14, m13]
---

# ADR-0010 — secret redaction policy

## Context

S14 added `bash`. Once the agent can run shell commands, every span we record
is a potential secret leak: env vars in `env`, AWS keys in `aws sts ...`, GitHub
tokens in `gh auth status`, Bearer headers from `curl -v`, private key blocks
from `cat ~/.ssh/id_rsa`. The notes HTML artifact (D4, ADR-0007) is meant to be
shareable. Today, sharing it would also share whatever the user accidentally
ran through the agent.

We have two questions to answer:

1. **Where does redaction live?** Source (every tool scrubs its own output)
   or sink (one module scrubs at the trust boundary)?
2. **What does redaction look like?** Black bars (`***`), salted hashes,
   stable placeholders, or remove-the-line entirely?

The security-engineering skill is clear on (1): apply controls at the trust
boundary, not at every call site. One module to test, one place to find bugs.

## Decision

### Where: redact at the sink

`src/tern/obs/redact.py` defines `Redactor`. `NDJSONSpanSink` instantiates one
per session and calls `_redactor.scrub_obj(payload)` immediately before
`json.dumps`. That is the choke point — every span and every notes-HTML row
flows through it. Tools stay dumb: they emit raw output, the sink scrubs it.

Implication: tools that *want* to surface a secret to the model on purpose
(none today) cannot, because the sink rewrites the span we send back. That is
the right default. If we ever need an exception, it is an explicit opt-out per
span, not a per-tool rule.

### What: stable per-session placeholders

Each redacted secret becomes `<KIND_N>` where `KIND` is the pattern label
(`AWS_ACCESS_KEY`, `GITHUB_TOKEN`, `OPENAI_KEY`, `BEARER_TOKEN`, `KV_PASSWORD`,
`PRIVATE_KEY_BLOCK`, `HIGH_ENTROPY`) and `N` is a per-session counter scoped
to that secret value. Same secret seen twice in the same session ⇒ same
placeholder. Different secrets ⇒ different placeholders.

Why stable, not random:
- Debug spans stay readable. If `<AWS_ACCESS_KEY_0>` shows up in turn 3 and
  turn 5, you can tell it is the same key without having seen the original.
- Cross-row correlation in the notes HTML still works — a secret reused
  across runs lights up consistently.
- It does not leak the secret itself. The placeholder is opaque outside the
  session; the counter resets at session boundary.

Why not hashes / black bars / line-deletion:
- Hashes (even salted) are still a fingerprint. We don't need fingerprints.
- Black bars (`****`) destroy structure — the model loses the shape of what
  it was reading and can't reason about "there are two distinct keys here."
- Deleting whole lines wrecks the tool output (an `env` listing full of holes
  is useless to the model and to debugging).

### Pattern catalogue (ordered, specific-first)

1. AWS access key (`AKIA[A-Z0-9]{16}`) — surgical, low false-positive.
2. GitHub tokens (`ghp_…`, `gho_…`, `ghu_…`, `ghs_…`, `ghr_…`).
3. OpenAI keys (`sk-[A-Za-z0-9]{20,}`).
4. Bearer tokens (`Authorization: Bearer …`, case-insensitive).
5. Key=value password / secret / token / api[_-]?key pairs.
6. PEM-style private key blocks (whole `-----BEGIN … PRIVATE KEY-----` … `END`).
7. High-entropy bare strings (32+ chars, mixed case + digits) — last, lowest
   confidence, runs only on substrings none of the above caught.

Order matters. We want `AKIAIOSFODNN7EXAMPLE` labeled `AWS_ACCESS_KEY`, not
`HIGH_ENTROPY`. Specific labels make incident triage tractable.

### Always-on, with a kwarg escape hatch

`NDJSONSpanSink(session_id, *, cwd=None, redact=True)`. Default is on. The
`redact=False` path exists for unit tests that need to assert raw payload
shape; production code never sets it. Backward compatible (kwarg with default).

## Alternatives considered

- **Source-side redaction (every tool scrubs).** Rejected. Eight tools today,
  more tomorrow, every one a potential bug. Skill says: trust boundary.
- **Allow-list instead of deny-list.** Rejected. We don't know what secret
  shapes the user has. We do know what common ones look like. Allow-listing
  "non-secret" content is impossible.
- **Run a real secrets scanner (truffleHog / gitleaks).** Considered, deferred.
  Heavyweight, off-by-default in a CLI agent's hot path. Revisit if our regex
  set proves inadequate; the sink is the right place to plug one in.
- **Deletion / blanking.** See above — destroys structure, breaks model
  reasoning, harder to debug.

## Consequences

Good:
- Notes HTML artifact (D4) is shareable by default. The whole point of D4 was
  "leave a trail you can show someone"; without redaction, that trail is a
  liability.
- One module, ~80 LOC, 9 unit tests. Easy to extend (add a pattern, add a
  test). Easy to audit.
- Stable placeholders mean session debugging still works on redacted spans.

Bad / accepted risk:
- Regex-based detection is best-effort. A non-standard secret format slips
  through. Mitigation: the high-entropy fallback catches the long-and-random
  cases; users running secrets through the agent should review before sharing
  notes anyway.
- Performance: every span pays a few regex passes. Measured: negligible at
  current span volume; revisit only if we see >1k spans/sec.

## References

- ADR-0007 (live HTML notes — the artifact this protects)
- security-engineering skill: trust boundaries, defense in depth
- `src/tern/obs/redact.py`, `src/tern/obs/sink.py`
- `tests/test_redact.py`
