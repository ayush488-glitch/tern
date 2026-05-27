---
title: aider
type: entity
created: 2026-05-27
updated: 2026-05-27
sources: [../sources/ref-aider.md]
tags: [reference, python, coding-agent]
---

# aider

Mature Python coding agent. Most directly relevant prior art. ~700 files, production-grade bash/edit-file/git workflow.

Repo (cloned, gitignored): `.scratch/grounding/refs/aider`.

## What we lift verbatim
- **Reflection retry loop**: parse-error / lint-error / test-failure flows back as next user turn. Single feature making a coder agentic.
- **SEARCH/REPLACE edit blocks** + fuzzy matcher (`search_replace.py`). Tolerates whitespace drift. Lifted nearly verbatim.
- **Few-shot exemplar in system prompt** showing exact edit format on toy task.
- **Commit-per-edit + HEAD snapshot for undo**. Aider's `commit_before_message` invariant.
- `ChatChunks` separation (system / examples / repo_map / done / cur / reminder), each independently cacheable.

## What we adapt
- Repo map (PageRank over symbol graph): too heavyweight for v1. Start with ctags + ripgrep on mentioned identifiers; upgrade to PageRank when benchmarks demand it. Lift the token-budgeted binary-search rendering loop and mtime-keyed cache.
- `ModelSettings` dataclass + JSON metadata file: keep. The if-ladder of name-substring defaults: replace with declarative `profiles.yaml` consumed by Tern's cost router.
- GitRepo abstraction layout (one class wrapping GitPython): keep.

## What we skip
- LLM-generated commit messages (low signal, costs a call). Use deterministic `tern: <tool> on <files> · turn <id>`.
- `--dirty-commits` auto-stash (surprising). Refuse to edit dirty files; surface conflict.
- Full tree-sitter language pack v1 (license + size + maintenance tax).
- Tight coupling to litellm. Wrap behind Tern's Provider Protocol so litellm = ONE backend, not THE abstraction.

## Three things Tern does that aider can't
1. Per-turn cost router (D1). Aider hard-codes edit_format and capabilities per model.
2. Replay/branch as primitive (D3). Aider's `commit_before_message` is one-way undo.
3. Skills as plugins (D2). Aider stuffs everything into one main_system per coder subclass.

See [sources/ref-aider.md](../sources/ref-aider.md) for the full extraction.
