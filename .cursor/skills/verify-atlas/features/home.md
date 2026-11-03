# Home and source overview

The home page is the table of every catalogue row. Source counts are the filter options and the catalogue list under the table.

## Sub-features

- Share bars in `section.share` (`#share-heading`).
- Filters: `#family-search`, `#area-filter`, `#lens-filter`, `#source-filter`, `#lean-filter`, and `#filter-reset`.
- Row count in `#shown-count`. The unfiltered text is `Showing 448 of 448`.
- Table `table[data-family-table]`. OpenAI rows are `tr[data-source="openai-math"]` with ids `f-001` and so on. AlphaProof rows are `tr[data-source="alphaproof-nexus"]`. Anthropic rows are `tr[data-source="anthropic"]`.
- Catalogue sentences in `ul.catalogue`: `373 families and 721 manuscripts`, `71 Lean files`, `4 releases`.
- Source index at `/math-release-atlas/source/`, then the OpenAI page at `/math-release-atlas/source/openai-math/`.

## How to get to it (user POV)

Open the site root. The header brand "Math Release Atlas" links to `/math-release-atlas/`. The primary nav link "Table" is the same page. "Sources" goes to the source index. That page links "OpenAI Math catalogue", "AlphaProof Nexus counts and scope notes", and "Anthropic releases".

## Driving it with Playwright

`node .cursor/skills/verify-atlas/scripts/drive-home.mjs` does this against the preview port:

1. Open `http://127.0.0.1:4321/math-release-atlas/` and wait until `#family-search` is visible. The title is `Math Release Atlas`.
2. Read `#source-filter option[value="openai-math"]`, `option[value="alphaproof-nexus"]`, and `option[value="anthropic"]`. The labels are `OpenAI Math (373)`, `AlphaProof Nexus (71)`, and `Anthropic (4)`.
3. Read `ul.catalogue` for `373 families and 721 manuscripts`, `71 Lean files`, and `4 releases`.
4. Select `openai-math`. `#shown-count` becomes `Showing 373 of 448`, 373 OpenAI rows stay visible, and every other `tbody tr[data-source]` is hidden.
5. Select `alphaproof-nexus`. `#shown-count` becomes `Showing 71 of 448`.
6. Select `anthropic`. `#shown-count` becomes `Showing 4 of 448`.
7. Click `#filter-reset`. `#shown-count` returns to `Showing 448 of 448`.
8. Click the nav link named `Sources`, then the link named `OpenAI Math catalogue`. The URL ends in `/source/openai-math/`, `h1` is `Manuscript catalogue`, and `p.summary-lead` contains `373 result families and 721 manuscripts`.

Screenshots and HTML go to `/tmp/verify-atlas-evidence/`. `drive-result.txt` lists each filter and the shown-count it left.

## Gotchas

- The filter script is `src/scripts/table.ts`, loaded as a module. Without JavaScript the noscript note says the full table is still listed, and `#shown-count` stays on the server-rendered total. A run that only reads the first paint does not see a filter result. Wait for the module, then select.
- The unfiltered total is 448 because the table mixes 373 families, 71 Lean files, and 4 releases. Filtering OpenAI does not show 373 of 373.
- Open the base path `/math-release-atlas/`, not `/`. Astro does not serve the table at the host root.
- The option labels and the 373 / 71 / 4 sentences are rendered from `data/families.json`. A catalogue change that moves those counts makes this journey fail until the expected text is updated from the data.
