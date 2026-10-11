# Changelog

## 0.4.6

- The home page leads with the share bars and a one-line table. Dates stay on one line. At a narrow width the bars and captions shrink, using a shorter caption taken from the same counts.
- Anthropic gap badges read "Not in the comparator", "Not formalized", and "Noted". AlphaProof gap rows state the paper counts in plain English. The checks read those sentences and the data fields.
- Family pages and the source pages lead with a badge, a plain-English status, and one summary. Manuscripts, Lean files, the comparator, and pinned commits sit in grouped receipts. The source index links an OpenAI Math page.
- A release whose notes say some claims are not formalized is drawn in the middle color. The legend says "not the whole claim". The alt says "135 main result".
- The card, the alt, and the built pages go through the overclaim scan.
- Local builds need Node.js 22.12 or newer and `pip install -r requirements.txt`.

## 0.4.5

- The share card shows the portion of each catalogue that has Lean files: one percent bar per registered source, a headline, and a sentence built from the catalogue counts. The percent is printed beside the bar. Family catalogues split Lean status into a main result, a comparator challenge, and paper only. A file catalogue keeps the paper gap in the denominator. A release list counts releases that include Lean files and labels a formalization as a formalization, including Fermat's Last Theorem.
- The image alt says that percent is the share with Lean files.
- The generated image alt describes that card. It names every registered source, states that Fermat's Last Theorem is a formalization, and states that the atlas is unofficial and not affiliated with the registered organizations. It stays within 420 characters. Gap statuses such as per-row provenance stay on the source pages.
- The build fails when an image alt is over 420 characters, a description is over 200, a Twitter title is over 70, or an image URL is not absolute https.

## 0.4.4

- Lens tags cover AlphaProof Nexus and Anthropic records as well as OpenAI Math families. Four math-subject lenses — number theory, combinatorics, algebraic geometry, and analysis — are applied only where the pinned upstream text supports them. Each tag has a why and a source URL.
- The citation graph states that its edges come from OpenAI Math manuscripts only. AlphaProof Nexus and Anthropic records have no citation data in this atlas. No cross-source edge was added.
- Home, family, and lens rows link to the upstream file or paper at the pinned commit. A short Notes link still reaches the atlas source page. Each OpenAI family links to its overview.tex entry, and every manuscript PDF is listed beside that entry. Anthropic paper links name arXiv v1.
- Fermat's Last Theorem stays labelled a formalization.
