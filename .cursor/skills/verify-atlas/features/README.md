# Surfaces

The harness is Playwright against the local preview, plus `scripts/check.py` for the pins. Routes use the `/math-release-atlas/` base path and a trailing slash.

| Feature | File | What a run drives |
| --- | --- | --- |
| Home and source overview | [home.md](home.md) | `node .cursor/skills/verify-atlas/scripts/drive-home.mjs` |
| Citation graph | [graph.md](graph.md) | Playwright on `/graph/` |
| Family page | [family.md](family.md) | Playwright on `/f/001/` |
| Pin integrity | [pins.md](pins.md) | `python3 scripts/check.py --self-test --source --verify-upstream` |
