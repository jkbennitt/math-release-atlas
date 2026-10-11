# Changelog

## 0.4.5

- The generated image alt text stays within 300 characters so X can validate the summary card. It still names every registered source, states that Fermat's Last Theorem is a formalization, and states that the atlas is unofficial and not affiliated with the registered organizations. Gap statuses such as per-row provenance stay on the source pages.
- The build fails when an image alt is over 420 characters, a description is over 200, a Twitter title is over 70, or an image URL is not absolute https.

## 0.4.4

- Lens tags cover AlphaProof Nexus and Anthropic records as well as OpenAI Math families. Four math-subject lenses — number theory, combinatorics, algebraic geometry, and analysis — are applied only where the pinned upstream text supports them. Each tag has a why and a source URL.
- The citation graph states that its edges come from OpenAI Math manuscripts only. AlphaProof Nexus and Anthropic records have no citation data in this atlas. No cross-source edge was added.
- Home, family, and lens rows link to the upstream file or paper at the pinned commit. A short Notes link still reaches the atlas source page. Each OpenAI family links to its overview.tex entry, and every manuscript PDF is listed beside that entry. Anthropic paper links name arXiv v1.
- Fermat's Last Theorem stays labelled a formalization.
