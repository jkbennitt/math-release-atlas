# Home and source overview

The home page is the table of every catalogue row. Source counts are the filter options and the catalogue list under the table.

## Sub-features

- Share bars in `section.share` (`#share-heading`).
- Filters: `#family-search`, `#area-filter`, `#lens-filter`, `#source-filter`, `#lean-filter`, and `#filter-reset`.
- Row count in `#shown-count`. The unfiltered text is `Showing 467 of 467`.
- Table `table[data-family-table]`. OpenAI rows are `tr[data-source="openai-math"]` with ids `f-001` and so on. AlphaProof rows are `tr[data-source="alphaproof-nexus"]`. AlphaEvolve rows are `tr[data-source="alphaevolve"]` with ids `ae-<anchor>`. Anthropic rows are `tr[data-source="anthropic"]`.
- Catalogue sentences in `ul.catalogue`: `373 families and 721 manuscripts`, `71 Lean files`, `18 notebook constructions`, `5 releases`.
- Source index at `/math-release-atlas/source/`, then the OpenAI page at `/math-release-atlas/source/openai-math/`, the AlphaEvolve page at `/math-release-atlas/source/alphaevolve/`, and the Anthropic page at `/math-release-atlas/source/anthropic/`.

## How to get to it (user POV)

Open the site root. The header brand "Math Release Atlas" links to `/math-release-atlas/`. The primary nav link "Table" is the same page. "Sources" goes to the source index. That page links "OpenAI Math catalogue", "AlphaProof Nexus counts and scope notes", "AlphaEvolve notebook constructions", and "Anthropic releases".

## Driving it with Playwright

`node .cursor/skills/verify-atlas/scripts/drive-home.mjs` does this against the preview port:

1. Open `http://127.0.0.1:4321/math-release-atlas/` and wait until `#family-search` is visible. The title is `Math Release Atlas`.
2. Read `#source-filter option[value="openai-math"]`, `option[value="alphaproof-nexus"]`, `option[value="alphaevolve"]`, and `option[value="anthropic"]`. The labels are `OpenAI Math (373)`, `AlphaProof Nexus (71)`, `AlphaEvolve (18)`, and `Anthropic (5)`.
3. Read `ul.catalogue` for `373 families and 721 manuscripts`, `71 Lean files`, `18 notebook constructions`, and `5 releases`.
4. Select `openai-math`. `#shown-count` becomes `Showing 373 of 467`, 373 OpenAI rows stay visible, and every other `tbody tr[data-source]` is hidden.
5. Select `alphaproof-nexus`. `#shown-count` becomes `Showing 71 of 467`.
6. Select `alphaevolve`. `#shown-count` becomes `Showing 18 of 467`.
7. Select `anthropic`. `#shown-count` becomes `Showing 5 of 467`.
8. Click `#filter-reset`. `#shown-count` returns to `Showing 467 of 467`.
9. Click the nav link named `Sources`, then the link named `OpenAI Math catalogue`. The URL ends in `/source/openai-math/`, `h1` is `Manuscript catalogue`, and `p.summary-lead` contains `373 result families and 721 manuscripts`.
10. Go back to Sources and open `AlphaEvolve notebook constructions`. `h1` is `AlphaEvolve`. `#alphaevolve-counts` contains `18 constructions.`, `15 maths problems.`, `19 notebooks.`, and `0 Lean files.` The badge text is `Checked by notebook`.
11. Go back to Sources and open `Anthropic releases`. `h1` is `Anthropic`. The page names FlashProve and its commit, and `#anthropic-counts` contains `flashprove: 29566 Lean files.`

Screenshots and HTML go to `/tmp/verify-atlas-evidence/`. `drive-result.txt` lists each filter and the shown-count it left.

## Gotchas

- The filter script is `src/scripts/table.ts`, loaded as a module. Without JavaScript the noscript note says the full table is still listed, and `#shown-count` stays on the server-rendered total. A run that only reads the first paint does not see a filter result. Wait for the module, then select.
- The unfiltered total is 467 because the table mixes 373 families, 71 Lean files, 18 notebook constructions, and 5 releases. Filtering OpenAI does not show 373 of 373.
- Open the base path `/math-release-atlas/`, not `/`. Astro does not serve the table at the host root.
- The option labels and the 373 / 71 / 4 sentences are rendered from `data/families.json`. A catalogue change that moves those counts makes this journey fail until the expected text is updated from the data.
