---
name: verify-atlas
description: >-
  Check the Math Release Atlas Astro site on its GitHub Pages surface
  (base path /math-release-atlas/, local preview of dist). Use after a change
  to the home table, the /graph/ page, a family or source page, or the pin
  checks in scripts/check.py.
---

# Verify the Math Release Atlas

The site is the Astro app in this repo. Pages are served under `/math-release-atlas/` with a trailing slash (`astro.config.mjs` sets `base` and `trailingSlash: "always"`). A local preview serves the `dist/` produced by `npm run build`. Node.js 22.12 or newer is required.

Run the helpers from the repo root. State is `/tmp/verify-atlas-run` (`VERIFY_ATLAS_STATE`). Evidence is `/tmp/verify-atlas-evidence` (`VERIFY_ATLAS_EVIDENCE`). The port is 4321 (`VERIFY_ATLAS_PORT`).

## Launch

From the repo root:

```bash
python3 -m pip install -r requirements.txt
npm ci
npm run build
npm run preview -- --host 127.0.0.1 --port 4321
```

`npm run build` runs `prebuild` (`scripts/merge.py`, `scripts/check.py --self-test --source`, `scripts/og_card.py`) and then `astro build`. The preview serves `dist/` at `http://127.0.0.1:4321/math-release-atlas/`.

The same sequence, in the background, with the pid recorded:

```bash
bash .cursor/skills/verify-atlas/scripts/launch.sh
```

It refuses to start when port 4321 is already taken. It does not stop that other process.

Ready means a GET of `http://127.0.0.1:4321/math-release-atlas/` returns the built home page: HTTP 200, `<title>Math Release Atlas</title>`, `id="family-search"`, and `data-family-table`. An open port with any other body is not ready. `launch.sh` curls that URL for up to 60 seconds and compares those markers. The preview log is `$VERIFY_ATLAS_EVIDENCE/preview.log`.

`launch.sh` records `git rev-parse HEAD` and `git status --porcelain` after the build. It exits if the worktree is dirty, because the preview would not be that commit.

CI runs two commands before `npm run build` so the graph accessibility check can draw HTML inside a canvas:

```bash
npx playwright install-deps chromium
bash scripts/install_chrome157.sh
```

`install_chrome157.sh` downloads Chrome for Testing `157.0.8103.15` (sha256 `ab9dd0ba103be79cc602962d8b21e285f26731a5115c1a759a0814da1346b54d`) to `/tmp/chrome157/chrome-linux64/chrome`. `launch.sh` does not download it. If that binary is already there, `npm run build` launches it and the check logs `graph a11y: drawable`. Without it, a local build uses another browser and logs `graph a11y: fallback`, or, when no browser launches, logs `graph a11y: skipped: no browser` and continues. In CI a missing binary, a launch failure, a skip, or fallback mode fails the build.

Teardown is `bash .cursor/skills/verify-atlas/scripts/cleanup.sh`.

## Doctor

```bash
bash .cursor/skills/verify-atlas/scripts/doctor.sh
```

Read-only. It checks:

- The preview pid recorded by `launch.sh` is still running.
- `git rev-parse HEAD` is still that commit, and `git status --porcelain` is still empty.
- `dist/index.html` still has the sha256 recorded at launch.
- Port 4321 has a listener, that listener is the preview pid or a descendant of it (parent walk, not a process-name search), and the listener's cwd is this repo.
- The body of `http://127.0.0.1:4321/math-release-atlas/` is byte-for-byte `dist/index.html` and still contains `id="family-search"` and `data-family-table`. The saved body is `$VERIFY_ATLAS_EVIDENCE/doctor-home.html`.
- `python3 scripts/check.py --self-test --source --verify-upstream` exits 0. Output is `$VERIFY_ATLAS_EVIDENCE/check-py.txt`.

`--verify-upstream` needs a network. It sparse-fetches the commits named in `data/upstream.json`, `data/alphaproof.json`, and `data/anthropic.json` and fails if a snapshot differs. It does not edit those pins.

## Drive

The harness is Playwright, launched from `drive-home.mjs` with the repo's `playwright` dependency. It uses `/tmp/chrome157/chrome-linux64/chrome` when that file exists, otherwise Playwright's Chromium (`npx playwright install chromium` once if that launch cannot find a browser). Install the pinned Chrome with `bash scripts/install_chrome157.sh` when you want the same browser CI uses. System libraries for that binary come from `npx playwright install-deps chromium`.

```bash
node .cursor/skills/verify-atlas/scripts/drive-home.mjs
```

That script drives the home and source overview. The other routes below are the same harness: open the URL, act, then read the resulting state. Counts below are the current catalogue: OpenAI Math 373 families and 721 manuscripts, AlphaProof Nexus 71 Lean files, AlphaEvolve 18 notebook constructions, Anthropic 5 releases. The home table has 467 rows (373 + 71 + 18 + 5).

| Route | What to read |
| --- | --- |
| `http://127.0.0.1:4321/math-release-atlas/` | `#family-search`, `#source-filter` options `OpenAI Math (373)`, `AlphaProof Nexus (71)`, `AlphaEvolve (18)`, `Anthropic (5)`, `ul.catalogue`, `#shown-count`, `table[data-family-table]` |
| `http://127.0.0.1:4321/math-release-atlas/graph/` | `h1` "Citation graph", the sentence "119 directed links among 125 families in this catalogue.", the sentence that AlphaEvolve records have no citation data, `svg.graph-map`, `ul.edge-list` |
| `http://127.0.0.1:4321/math-release-atlas/f/001/` | `article.family`, `h1[data-upstream="title"]`, `a.direct-upstream` |
| `http://127.0.0.1:4321/math-release-atlas/source/openai-math/` | `h1` "Manuscript catalogue", `p.summary-lead` "373 result families and 721 manuscripts" |
| `http://127.0.0.1:4321/math-release-atlas/source/alphaproof-nexus/` | `#alphaproof-counts` containing "71 Lean files in total." |
| `http://127.0.0.1:4321/math-release-atlas/source/alphaevolve/` | `h1` "AlphaEvolve", `#alphaevolve-counts` "18 constructions.", "19 notebooks.", "0 Lean files.", badge "Checked by notebook" |
| `http://127.0.0.1:4321/math-release-atlas/source/anthropic/` | `#anthropic-counts`, and the FlashProve commit on the page |

The home script's path: load `/`, read the four option labels and the catalogue sentences, select each `#source-filter` value and read `#shown-count` plus the visible `tr[data-source]` rows, click `#filter-reset`, click the nav link "Sources", then click "OpenAI Math catalogue" and read the source page lead. It then opens the AlphaEvolve source page, the Anthropic source page, `/graph/`, and `/f/001/`.

## Evidence

Keep it under `/tmp/verify-atlas-evidence` (or `VERIFY_ATLAS_EVIDENCE`). Cleanup does not delete that directory.

| File | What it is |
| --- | --- |
| `head.txt`, `built_at.txt` | Commit and UTC time of the build |
| `preview.log` | Preview process output |
| `doctor-home.html` | Home response body saved by doctor |
| `check-py.txt` | `scripts/check.py --self-test --source --verify-upstream` |
| `home.html`, `home.png` | Home page after load |
| `home-openai-math.png`, `home-alphaproof-nexus.png`, `home-alphaevolve.png`, `home-anthropic.png` | Table after each source filter |
| `source-openai.html`, `source-openai.png` | OpenAI source page after the click from Sources |
| `source-alphaevolve.html`, `source-alphaevolve.png` | AlphaEvolve source page |
| `source-anthropic.html`, `source-anthropic.png` | Anthropic source page, including FlashProve |
| `graph.html`, `graph.png` | Citation graph |
| `family-001.html`, `family-001.png` | Family 001 |
| `drive-result.txt` | Action and the resulting shown-count or lead text |

### Proof standards

Drive a real user path. Record the action and the state it leaves, not only that a URL returned 200. A filter action is matched to `#shown-count` and the rows still visible. A navigation action is matched to the heading and the count sentence on the page you land on. A failed journey stays failed; do not drop a selector or a count to make the script exit 0.

## Cleanup

```bash
bash .cursor/skills/verify-atlas/scripts/cleanup.sh
```

It reads the pid `launch.sh` wrote. It signals that pid and its children (`pgrep -P` on that pid). It does not search by process name. It will not signal pid 1, and it stops if the recorded pid's command line is not `npm`, `astro`, or `node`. Evidence stays where it is.

## Helpers

| Script | Invocation |
| --- | --- |
| `.cursor/skills/verify-atlas/scripts/launch.sh` | `bash .cursor/skills/verify-atlas/scripts/launch.sh` |
| `.cursor/skills/verify-atlas/scripts/doctor.sh` | `bash .cursor/skills/verify-atlas/scripts/doctor.sh` |
| `.cursor/skills/verify-atlas/scripts/drive-home.mjs` | `node .cursor/skills/verify-atlas/scripts/drive-home.mjs` |
| `.cursor/skills/verify-atlas/scripts/cleanup.sh` | `bash .cursor/skills/verify-atlas/scripts/cleanup.sh` |
| `scripts/install_chrome157.sh` | `bash scripts/install_chrome157.sh` |

Feature notes are in `.cursor/skills/verify-atlas/features/`.
