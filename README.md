# Math Release Atlas

Unofficial index of the result families in the manuscript collection at
github.com/openai/math. Not affiliated with OpenAI.

The site is a table of every family at a pinned upstream commit: subject,
manuscripts, dates, and Lean status, with links back to the upstream PDFs.
Each row links to a family page. Lens pages group the families that have a
hand-written tag. A family with no curated note still shows community status
claimed. A Lean badge means the upstream catalogue lists a formalized main
result or only a Comparator challenge. Upstream marks that review status
unchecked. A Lean check is not peer review and not a laboratory result.

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
the commit changed, a read-only job regenerates the data files and runs
the build and the wording checks. A second job does not run the install or
any repository script. It commits that data and opens or updates a pull
request that records whether those checks passed. It does not merge that
pull request. The site updates only after the pull request is merged and
the Pages workflow runs.

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
`source`. Community status ids are `claimed`, `community-checking`,
`independently-checked`, `disputed`, and `retracted`. Any status other than
`claimed` needs evidence: an http or https URL, a `YYYY-MM-DD` date, and a
short neutral note of at most 25 words. That status is recorded only when
`data/curated/status-approvals.yaml` has an entry with the same family id,
status, evidence URL, date, and note, and with approver `jkbennitt`. Editing
the note or the date after that entry is written fails Guard. The file starts
empty. `claimed` may omit evidence. The same three evidence fields are
required on a history entry whose status is not `claimed`, and that entry
needs its own allowlist match. The vocabulary file is
`data/curated/community-status.yaml`. Every status change must be approved by
Jason (repo policy). Branch protection is off. `.github/CODEOWNERS` names
@jkbennitt on `data/curated/`. The weekly sync does not write community
status. See `CONTRIBUTING.md`. Curated text uses the same sentence check as
the rest of the site. A hostile note fails the build. A whole word and its
plurals and inflections are matched. A hyphenated compound is left alone, as
is one stored two-word technical phrase.

Citation edges are read from `OAI:` keys in upstream manuscript `.tex` and
`.bib` files and stored when the catalogue is built. The merge step turns
those edges into `cites` and `cited_by`. Each edge keeps the upstream file
URL as its receipt. Counts on the graph page come from that merged data.

When a shared-topic link is rendered, the label is “our grouping, not a
citation.”

## Checks

The build checks that derived counts match the upstream README sentence. For
commit `adc7f1241b42` it also requires 372 families, 722 manuscripts, and the
Lean split 127 formalized main results / 108 comparator-only / 137 with no
Lean formalization.

A sentence fails the build when a guarded problem itself is what a claim verb
addresses. The problems and the verbs are listed separately below, because
putting both in one sentence is what the check rejects. A negation anywhere
in the sentence does not exempt it. The only exemption is an exact caution
sentence from the fixed list (whitespace collapsed, trailing period
ignored). A longer sentence that merely contains a caution is not exempt.

The incompressible-flow name does not count when the next word is energy,
inequality, estimate, bound, computation, scheme, solver, or approximation,
and the sentence does not also say regularity, smoothness, smooth (unless
the next word is data), blow up, blow-up, blowup, existence, well-posed, or
well-posedness. When a claim verb is also present, the word smooth cancels
that exception even if the next word is data. A space, hyphen, or dash may
separate the words blow and up, and the words well and posed. A sentence
that only names an energy inequality for smooth data, and has no claim verb,
still passes.

Guarded problems: RH, the dotted form R.H., the Riemann Hypothesis,
Riemann's hypothesis, Riemann-Hypothesis (hyphen or dash), Navier–Stokes
(hyphen, dash, or space), the Clay problem, the Clay prize, the Millennium
problem, Millennium-problem, and the Millennium prize.

Claim verbs: prove, proves, proved, proving, proven, disprove, disproves,
disproved, disproving, disproven, confirm, confirms, confirmed, confirming,
proof, proofs, proof of, proofs of, proof for, proofs for, proof complete,
complete proof, establish, establishes, established, establishing, solution,
solutions, a solution to, solution of, resolution, resolutions, resolve,
resolves, resolved, resolving, settle, settles, settled, settling, solve,
solves, solved, solving, crack, cracks, cracked, cracking, finish, finishes,
finished, and finishing. Further claim
words are true, holds, follows, verify, verifies, verified, verifying, show,
shows, showed, shown, showing, demonstrate, demonstrates, demonstrated,
demonstrating, win, wins, won, winning, award, awards, awarded, awarding,
correct, obtain, obtains, obtained, obtaining, done, and the phrase “a theorem”.

The sentence check applies to authored pages, curated notes, fixed cautions,
and built HTML, including text inside an element marked as an upstream
quotation. That text is left out only when it exactly equals that family's
upstream title or id. An upstream summary or manuscript title that fails the check is left out of
the built pages. The text stays in the catalogue data, and the fixed caution
still appears. alt, title, meta content, aria-label, aria-description,
placeholder, and data-* attributes are included, quoted or unquoted. In built
HTML, a data-* value is left out only when it exactly equals that family's
upstream title or id. The citation graph has no such exemption. Curated
evidence URLs must be http or https, with no spaces, quotes, or angle brackets.
Before either check, text is NFKC-normalized and soft hyphens and zero-width
characters are removed.

The digest check covers the whole repository and the built HTML with those
quotations left in place. It matches plurals, adjective forms, and hyphenated
compounds, plus short compounds stored only as full-string digests, including
the abbreviated temperature form. A length-6 stem is ignored when the next
word is a stored math neighbor, or when a preceding neighbor is the entire
rest of the phrase. A further word after that preceding neighbor still
matches. The stems are not written in this repository.

`data/upstream.json` names a commit. Guard, Build, and the weekly sync
require that commit to be the default-branch HEAD of openai/math or an
ancestor of it (`git fetch --filter=blob:none origin HEAD`, then
`git merge-base --is-ancestor`), then sparse-fetch that commit and fail if
the snapshot differs. `generated_at` is ignored. A SHA that the host will
serve for the repository URL, but that is not on this history, fails the
ancestry check. While the recorded commit is the pinned one, the build also
requires a SHA-256 of the snapshot. `families.json` must be the merge of
that snapshot and the curated notes. Fixed cautions for families 002, 003,
032, 102, 103, 107, and 376 always render.

## License

Apache-2.0. See `NOTICE` and `UPSTREAM_LICENSE`.
