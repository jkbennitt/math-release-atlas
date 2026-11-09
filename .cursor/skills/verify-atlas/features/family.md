# Family page

Each OpenAI Math family has a page at `/math-release-atlas/f/<id>/`. Family `001` is the stable page to open first.

## Sub-features

- `article.family` and `h1[data-upstream="title"]`.
- Lean badge and the upstream review line in `p.status-line`.
- Meta line `Family 001` and a link to `/source/openai-math/`.
- Manuscript links `a.direct-upstream` inside the Manuscripts receipt.
- `blockquote.summary-lead[data-upstream="summary"]`.
- Back link `a[href$="#f-001"]` to the home row.

## How to get to it (user POV)

On the home table, open the result title in row `f-001`. The title is a link to `/math-release-atlas/f/001/`. The same id is linked from the citation graph when that family is on the map. "Back to the table" returns to `/math-release-atlas/#f-001`.

## Driving it with Playwright

`node .cursor/skills/verify-atlas/scripts/drive-home.mjs` opens family 001 from the home table after the graph page.

1. Open `http://127.0.0.1:4321/math-release-atlas/`.
2. Click `tr#f-001 a[data-upstream="title"]`.
3. Wait for the URL to end in `/f/001/`.
4. Read `article.family h1[data-upstream="title"]`. It is non-empty and matches the link text you clicked.
5. Read the meta line. It contains `Family 001`.
6. Read `a.direct-upstream`. At least one manuscript link is present, and its href contains `github.com/openai/math/blob/` and the pinned commit.
7. Save `family-001.html` and `family-001.png` under `/tmp/verify-atlas-evidence/`.

## Gotchas

- The title uses the catalogue's apostrophe. Compare the heading to the link you clicked, or to `data/families.json`, instead of retyping the character.
- Family pages exist for OpenAI ids only. AlphaProof, AlphaEvolve, and Anthropic rows link to their source sections, not to `/f/<id>/`. AlphaEvolve rows are notebook constructions.
- A caution, when the family has one, is `p.caution`. Family 001 has no caution element. Do not require one on this page.
