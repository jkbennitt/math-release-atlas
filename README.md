# Math Release Atlas

Unofficial index of two pinned catalogues. One is the result families in the
manuscript collection at github.com/openai/math. The other is the Lean files
in github.com/google-deepmind/alphaproof-nexus-results, read with arXiv
2605.22763. Not affiliated with OpenAI or Google DeepMind.

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

`npm run build` merges curated notes, checks counts and wording, draws the
link-preview card, and writes `dist/`.

## Link previews

The shared layout emits the page title and description as Open Graph and
Twitter Card tags, plus a canonical URL. Every URL is absolute and includes
`/math-release-atlas/`. `scripts/og_card.py` reads the family and manuscript
counts from `data/families.json`, and the AlphaProof Lean-file counts from
the same file, and writes `public/og.png` at 1200×630.
Astro copies that file into `dist/`. The card names both sources and those
counts. The image spells Erdos in ASCII because the card fonts have an empty
box for ő. The alt text is the same sentence as `preview_alt()` in
`scripts/atlaslib.py` and `previewImageAlt` in `src/lib/social.ts`: unofficial,
not affiliated with OpenAI or Google DeepMind. The dist check fails if any
built page is missing `og:image` or `twitter:card`, or if `og:image` is not
absolute. Package version 0.2.0.

To regenerate the catalogue from a clone that is already at the commit you
want:

```bash
python3 scripts/sync.py --checkout /path/to/openai-math
```

Omit `--checkout` to sparse-fetch openai/math HEAD and the AlphaProof Nexus
tree. The OpenAI fetch does not download the PDF tree. If both commits already
match `data/upstream.json` and `data/alphaproof.json`, the script exits
without writing and prints `Upstream commit is unchanged.` It never edits
`data/curated/`.

## Daily sync

`.github/workflows/sync.yml` runs every day at 10:17 UTC, and it can be
started by hand with “Run workflow”. It uses a GitHub-hosted `ubuntu-latest`
runner. It reads both upstream HEADs. When both commits match the ones recorded
in the catalogue, the job exits and does not open a pull request. When either
commit changed, a read-only job regenerates the data files and runs the
build and the wording checks. One pull request covers both catalogues. A second job does not run the install. It
commits that data. The pull-request filter and the branch plan in that job
run with the token removed from the environment. If one sync pull request from the
Actions app is already open on this repository, it updates that pull request
by number. A pull request from another repository is ignored. Two matching
pull requests stop the job. A human commit on the sync branch is left in
place, and the job opens a separate branch instead of replacing it. A commit
already on main does not count as an edit of the sync branch. A missing
comparison ref stops the job instead of updating the open pull request. It never
merges that pull request. The site updates only after the pull request is
merged and the Pages workflow runs.

The publish job pushes and opens the pull request with the default
`GITHUB_TOKEN`. GitHub creates Build and Guard runs for that pull request and
leaves them waiting for approval, so the pull request shows no status checks.
A push from that token does not start workflows at all. After the push, the
same job starts Build (`ci.yml`) and Guard (`guard.yml`) with
`workflow_dispatch` on the sync branch. That event runs the workflows and
attaches the checks to the commit. No personal access token is required.

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
@jkbennitt on `data/curated/`. The daily sync does not write community
status. See `CONTRIBUTING.md`. Curated text uses the same sentence check as
the rest of the site. A hostile note fails the build. A whole word and its
plurals and inflections are matched. A hyphenated compound fails when a part
is hostile or the parts join into a hostile word, and so does a split pair of
words. A stored hyphenated technical compound is left alone, as is a stored
two-word technical phrase. A stored whole token is left alone when the
inflection rule would split it into a hostile stem.

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

Two patterns fail anywhere in a sentence that names a guarded problem, with
no distance limit. They are proof or disproof followed by of, for, or
complete, and solution or solutions followed by to or of. A comma-separated
aside between solution and to or of fails the same way. A match inside a
longer proof compound still counts.

The solution pattern is waived only when the whole sentence matches one closed
template, ignoring case and trailing punctuation. The template is an optional
article, then one of scheme, operator, numerical, weak, Leray, mild, strong,
assistant, lemma, estimate, estimates, or approximate, then solution or
solutions, then of or to, then an optional “the”, then the incompressible-flow
name, then an optional equations or system. No further words are allowed.
Proof compounds are never waived. One pattern that is not waived still fails
the sentence, including a match inside a longer proof compound. The waived
positions have to be exactly the matches of those two patterns.

A second closed template waives only the four-token check. It never waives
the two patterns above. The template is an optional article, then the
incompressible-flow name, then solution or solutions, then scheme, schemes,
operator, operators, method, or methods, then an optional “is bounded” or
“are bounded”. No further words are allowed.

Before either template is applied, a space, no separator, or any hyphen or
dash between the two parts of that name is folded to one spelling. The dash
forms include the non-breaking hyphen, the em dash, and the fullwidth hyphen.

A claim noun within four tokens of a guarded problem name also fails, in
either order. Punctuation and possessives are ignored when the tokens are
counted. The nouns are proof, proofs, disproof, disproofs, solution,
solutions, resolution, and resolved. That nearer check waives solution or
solutions only when the whole sentence matches one of the two templates
above, and only for the incompressible-flow name. The pair “proof assistant”
is not a claim noun.

Guarded problems: RH, the dotted form R.H., the spaced form R H, the Riemann Hypothesis,
Riemann's hypothesis, Riemann-Hypothesis (hyphen or dash), Navier–Stokes
(hyphen, dash, space, or no separator), the Clay problem, the Clay prize, the Millennium
problem, Millennium-problem, and the Millennium prize.

Claim verbs: prove, proves, proved, proving, proven, disprove, disproves,
disproved, disproving, disproven, proof of, proof for, proof complete,
disproof of, solution to, solution of, confirm, confirms, confirmed, confirming,
establish, establishes, established, establishing, resolve,
resolves, resolved, resolving, settle, settles, settled, settling, solve,
solves, solved, solving, crack, cracks, cracked, cracking, finish, finishes,
finished, and finishing. Further claim
words are true, holds, follows, verify, verifies, verified, verifying, show,
shows, showed, shown, showing, demonstrate, demonstrates, demonstrated,
demonstrating, win, wins, won, winning, award, awards, awarded, awarding,
correct, obtain, obtains, obtained, obtaining, done, and the phrase “a theorem”.

The sentence check applies to authored pages, curated notes, fixed cautions,
and built HTML, including text inside an element marked as an upstream
quotation. That text is left out of the check only when it exactly equals
that family's upstream title, id, summary, or manuscript title, or when it
exactly equals a stored AlphaProof quotation. Only the text
nodes are left out. Attributes on that element and on elements inside it are
still checked. HTML comments inside that element are still checked. The page still shows it. Text that does not match fails the
check. A further check fails a sentence that places solved, solves, proves,
proved, resolves, or resolved within 48 characters of a result name, in either
order. Those names are Erdős, Erdos, OEIS, and Stacks. An exact quotation in
a `data-upstream` element is left out of that check. A longer sentence that
only contains the quotation is not left out. alt, title, meta content,
aria-label, aria-description, placeholder, and data-* attributes are included,
quoted or unquoted. In built HTML, a data-* value is left out only when it
exactly equals one of those same strings. The citation graph has no such
exemption. Curated
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

`data/upstream.json` names a commit. Guard, Build, and the daily sync
require that commit to be the default-branch HEAD of openai/math or an
ancestor of it (`git fetch --filter=blob:none origin HEAD`, then
`git merge-base --is-ancestor`), then sparse-fetch that commit and fail if
the snapshot differs. `generated_at` is ignored. A SHA that the host will
serve for the repository URL, but that is not on this history, fails the
ancestry check. While the recorded commit is the pinned one, the build also
requires a SHA-256 of the snapshot. `data/alphaproof.json` names its own
commit. The same ancestry check runs against
google-deepmind/alphaproof-nexus-results HEAD, then the recorded tree is
fetched and compared. `generated_at` and the snapshot digest field are
ignored in that comparison. While that commit is the pinned one, the build
requires 9 Erdős Lean files, 38 OEIS Lean files, 11 Stacks Lean files, and
13 AI collaborator Lean files. `families.json` must be the merge of
the OpenAI snapshot, the curated notes, and the AlphaProof snapshot.
Fixed cautions for families 002, 003,
032, 102, 103, 107, and 376 always render.

The AlphaProof page shows the paper OEIS count beside the repository file
count and labels the difference `not in repo / unexplained`. It shows the
paper attempted count beside the newline count in
`erdos_problems_attempted.txt` and labels that `352 vs 353`. It does not
fill either gap. The cross-source page lists a problem only when both
catalogues name that number. At these pinned commits that list is empty.
Per-row provenance is `MISSING`.

## License

Apache-2.0. See `NOTICE` and `UPSTREAM_LICENSE`. AlphaProof Nexus code is
Apache-2.0. Its other materials are CC-BY 4.0. OEIS-derived material is
CC BY-SA 4.0. The repository copyright notice names Google LLC. The
organization label on this atlas is Google DeepMind. That repository says
this is not an official Google product.
