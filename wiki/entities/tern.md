---
title: Tern (this project)
type: entity
created: 2026-05-27
updated: 2026-05-27
tags: [tern, project]
---

# Tern

A Python CLI coding agent in the spirit of Claude Code, with six baked-in differentiators (D1–D6). Open-source foundation under Antern brand.

## Identity
- Name: `tern` (also CLI binary)
- Repo: `/Users/ayushsingh/Desktop/coding-agent/`
- Language: Python 3.12
- Distribution: `pipx install tern`
- Provider: Bedrock first (existing creds), pluggable from day 1

## Differentiators
See [differentiators](../roadmap/differentiators.md). D1–D6 are not features — they're architectural commitments built into v1.

## Reference repos consulted
- [aider](aider.md) — primary lift source for Python coding-agent patterns
- [claude-code](claude-code.md) — TS clone, design DNA
- [browser-use](browser-use.md) — D5 browser tool
- [mcp-python-sdk](mcp-python-sdk.md) — D6 MCP client
- goose — turned out to be desktop UI + OIDC proxy on inspection; minor signal

## Brand
Antern is the company. Tern is the open-source project — short, ergonomic CLI binary, related but not a literal substring of Antern (no "we just chopped letters off"). Foundation now, branding later.

## Voice
Senior-engineer thinking out loud. Short sentences. Plain English. No em dashes. See AGENTS.md for the full tone guide.
