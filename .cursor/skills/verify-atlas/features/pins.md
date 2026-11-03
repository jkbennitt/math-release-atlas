# Pin integrity

`data/upstream.json` holds the commit and digest pins. `scripts/check.py` rebuilds the snapshots and compares them. The daily sync notes are produced by `scripts/sync.py`.

## Sub-features

- `python3 scripts/check.py --self-test` runs the guard fixtures, including the bounded git fetch retry and the zeta-tag sync note.
- `--source` checks the generated catalogue, authored text, and the Chrome for Testing pin in the workflows.
- `--verify-upstream` sparse-fetches the pinned commits and compares the snapshots.
- An empty `zeta_tag` or `zeta_tag_commit` in the sync note is the text `(missing)`.

## How to get to it (user POV)

There is no page for the pins. The home page links the OpenAI commit. The source pages show the pinned commits for OpenAI Math, AlphaProof Nexus, and Anthropic. The check is a terminal command, which is what CI runs in Guard and again inside `npm run build`.

## Driving it with check.py

From the repo root, with `python3 -m pip install -r requirements.txt` already done:

```bash
python3 scripts/check.py --self-test --source --verify-upstream
```

The command needs a network because `--verify-upstream` fetches the pinned upstreams. A passing run prints `checks passed` and exits 0. `doctor.sh` runs this and saves the output at `/tmp/verify-atlas-evidence/check-py.txt`.

Do not pass flags that skip `--self-test`, `--source`, or `--verify-upstream` when the goal is the same check CI runs. Do not edit `data/upstream.json` to make a mismatch disappear.

## Gotchas

- `--verify-upstream` reads the pins. It does not move a commit or a digest. A mismatch is a failed check.
- The fetch helper retries `git fetch` and `git clone` at most three times (one second, then two seconds). A checkout is not retried. A permanent failure still fails, after the third try.
- Guard does not run `npm run build`, so it does not launch Chrome. Build, Pages, and the sync build install `157.0.8103.15` and then run the graph check. The mode line `graph a11y: drawable` is part of that build, not part of this command.
