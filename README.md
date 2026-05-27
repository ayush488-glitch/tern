# Tern

A Python CLI coding agent in the spirit of Claude Code, with six baked-in differentiators:

- **D1** per-turn cost routing
- **D2** skills as first-class
- **D3** per-turn replay + branch
- **D4** live HTML notes artifact
- **D5** browser-use as a real tool
- **D6** MCP client built-in

Open-source foundation. Antern brand.

## Status

Pre-alpha. Skeleton only. See `wiki/roadmap/14-session-plan.md` for the build ladder and `docs/architecture.html` for the system architecture (single page, b&w, scales thumbnail → poster).

## Install (developer)

```bash
git clone https://github.com/antern-dev/tern
cd tern
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
tern --version
pytest
```

## Architecture

See `docs/architecture.html` (open in any browser) for the full system map.
See `AGENTS.md` for how this repo's wiki is structured and maintained.
See `wiki/index.md` for the catalog of every design page.

## License

Apache-2.0.
