# Math Release Atlas

Unofficial index of the result families in the manuscript collection at
github.com/openai/math. Not affiliated with OpenAI.

The site is a table of every family at a pinned upstream commit: subject,
manuscripts, dates, and Lean status, with links back to the upstream PDFs.
A Lean badge means the upstream catalogue lists a formalized main result or
only a Comparator challenge. Upstream marks that review status unchecked.
A Lean check is not peer review and not a laboratory result.

## Run locally

```bash
python3 -m pip install -r requirements.txt
npm install
npm run dev
```

Open the URL Astro prints. Pages are served under `/math-release-atlas/`,
the path GitHub Pages uses for this repository.

`npm run build` merges curated notes, checks counts and wording, and writes
`dist/`.

To regenerate the catalogue from a clone that is already at the commit you
want:

```bash
python3 scripts/sync.py --checkout /path/to/openai-math
```

Omit `--checkout` to sparse-fetch upstream HEAD. The fetch does not download
the PDF tree. If that commit already matches `data/upstream.json`, the script
exits without writing. It never edits `data/curated/`.

## Weekly sync

`.github/workflows/sync.yml` runs every Monday at 13:00 UTC, and it can be
started by hand with “Run workflow”. It uses a GitHub-hosted `ubuntu-latest`
runner. It reads upstream HEAD. When the commit is unchanged, it stops. When
the commit changed, it regenerates the data files, runs the build and the
wording checks, and opens a pull request that records whether those checks
passed. It does not merge that pull request. The site updates only after
the pull request is merged and the Pages workflow runs.

If the parsed family and manuscript counts disagree with the count sentence
in the upstream README, the pull request is still opened and the check fails.
Any other sync failure stops the job before a pull request is opened.

## Curated tags

Add `data/curated/362.yaml`. The generator will not overwrite it.

```yaml
id: "362"
lenses:
  - tag: plasma-kinetic
    why: "Charged particles coupled to an electromagnetic field."
    source: "Upstream family summary for 362, commit adc7f1241b42"
related:
  - to: "363"
    kind: shared-topic
    why: "Both are kinetic equations."
    source: "Hand grouping; not an upstream citation"
```

Lens tags are `condensed-matter`, `plasma-kinetic`, `fluids-continuum`,
`electronic-structure`, `quantum-information`, `gravity-qft`, and
`computation-hardness`. Each lens and each related link needs a non-empty
`source`. A community status of `community-confirmed`, `disputed`, or
`broken` needs an evidence list with a url, who, date, and a quote of at
most 25 words. `claimed` may have an empty evidence list. Curated text uses
the same sentence check as the rest of the site.

When a shared-topic link is rendered, the label is “our grouping, not a
citation.”

## Checks

The build checks that derived counts match the upstream README sentence. For
commit `adc7f1241b42` it also requires 372 families, 722 manuscripts, and the
Lean split 127 formalized main results / 108 comparator-only / 137 with no
Lean formalization.

A sentence fails the build when it names a guarded problem and also uses a
claim verb. The problems and the verbs are listed separately below, because
putting both in one sentence is what the check rejects. A negation anywhere
in the sentence does not exempt it. The only exemption is an exact caution
sentence from the fixed list (whitespace collapsed, trailing period
ignored). A longer sentence that merely contains a caution is not exempt.

Guarded problems: RH, the Riemann Hypothesis, Navier–Stokes (hyphen, dash,
or space), Clay, and Millennium.

Claim verbs: prove, proves, proved, proving, proof of, proofs of, resolve,
resolves, resolved, resolving, settle, settles, settled, settling, solve,
solves, solved, solving, crack, cracks, cracked, and cracking.

Published HTML and the repository text are also checked against SHA-256
digests of a fixed set of lowercase tokens. Those tokens are not written in
this repository. Fixed cautions for families 002, 003, 032, 102, 103, 107,
and 376 always render.

## License

Apache-2.0. See `NOTICE` and `UPSTREAM_LICENSE`.
