# Changelog

## 0.4.9

- Where the browser can draw HTML inside a canvas, the citation map labels are those HTML links. They stay in the page HTML, and each label still opens its family page. The earlier map is removed from the tab order there.
- A 3D view draws the same edges with those labels in the scene. A pause control stops the turn, and the view starts paused when the browser asks for reduced motion. The page can still scroll past that view. The list underneath is the same list as before.
- Browsers that cannot draw HTML inside a canvas keep the previous map. The 3D control stays hidden there.
- Three.js is bundled with the site. The graph page does not load a script, stylesheet, or font from another origin. The build checks that each map label is present in the HTML and that those asset URLs stay on this site.

## 0.4.8

- Anthropic's eth release is in the catalogue: a Lean formalization in the upstream repo of a deterministic 2^{o(n)}-time algorithm for 3-SAT, from eth/README.md and eth/MainResults.lean at formal-math 16a5ce41304f. The upstream README says this refutes the Exponential Time Hypothesis. MainResults.lean states that claim for Mathlib multi-stack Turing machines and says a random-access simulation and formula rewriting are not part of the Lean statements. The release is tagged computation-hardness from that file. At this commit the formal-math skip list is empty. Each Anthropic row's Source link goes to its Lean file at the pinned commit.

## 0.4.7

- OpenAI's comparator-challenge families are a Lean challenge statement. That segment's legend entry is "Lean challenge only". A release whose notes say some claims are not formalized stays "partly in Lean", including on a narrow screen. The two use different swatches, and the legend lists only the segments that appear. OpenAI's caption stays "135 result in Lean · 107 challenge only · 130 paper only".
- Share colors step in lightness, and the partly-in-Lean segment is hatched, so every segment stays distinct in grayscale. Each fill is at least 3:1 on #f3efe6. Neighboring fills stay at least 1.5:1 apart. The card and the home bars use the same swatches.
- On a narrow screen the share bars are 10px tall and the outline is removed, so the outline no longer covers the fill.
- Each home bar's screen-reader label is checked against the catalogue, the same way the percent and the caption are.
- The citation map stays visible on a narrow screen. It sits in a sideways-scrolling frame at least 900px wide, with the hint "Scroll or pinch to zoom." Cite lines, topic lines, and labels stay at least 3:1 on the light paper.

## 0.4.6

- The home page leads with the share bars and a one-line table. Dates stay on one line. At a narrow width the bars and captions shrink, using a shorter caption taken from the same counts.
- Anthropic gap badges read "Not in the comparator", "Not formalized", and "Noted". AlphaProof gap rows state the paper counts in plain English. The checks read those sentences and the data fields.
- Family pages and the source pages lead with a badge, a plain-English status, and one summary. Manuscripts, Lean files, the comparator, and pinned commits sit in grouped receipts. The source index links an OpenAI Math page.
- A release whose notes say some claims are not formalized is drawn in the middle color. Its caption says "partly in Lean", including on a narrow screen, and the legend uses the same words. A family catalogue still captions that color "challenge only". The alt says "135 main result".
- The card, the alt, and the home share section go through the overclaim scan and a whole-word ban on verified, verify, proved, proven, proof, confirmed, certified, and solved.
- The share bars use darker teal and tan, each at least 3:1 on the page, with a 1px ink outline. The built bars, percents, and captions are checked against the catalogue.
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
