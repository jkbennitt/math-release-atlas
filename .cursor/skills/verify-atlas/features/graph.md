# Citation graph

`/math-release-atlas/graph/` lists citation edges from OpenAI Math manuscripts and draws the same edges.

## Sub-features

- Intro and the sentence `119 directed links among 125 families in this catalogue.`
- SVG map `svg.graph-map` with `<title id="citation-map-title">`.
- Canvas map `canvas.graph-canvas` and `canvas.graph-webgl`. Family labels inside the canvas are `a.graph-label`.
- `#graph-3d` and `#graph-spin`. Both are `hidden` in the HTML until the browser can draw HTML inside a canvas.
- Edge list `ul.edge-list`. Each item links `f/<id>/` for the two families.
- Link to the cross-source page, `a[href$="/source/cross/"]`.

## How to get to it (user POV)

From any page, use the primary nav link "Graph". The home page also links "Citation graph" in the provenance line under the table.

## Driving it with Playwright

`node .cursor/skills/verify-atlas/scripts/drive-home.mjs` opens this page after the source pages.

1. Open `http://127.0.0.1:4321/math-release-atlas/graph/` and wait for `svg.graph-map`.
2. Read `h1`. It is `Citation graph`.
3. Read the paragraph that contains `directed links among`. At this catalogue it is `119 directed links among 125 families in this catalogue.`
4. Read the intro. It says AlphaEvolve records have no citation data in this atlas.
5. Count `ul.edge-list > li`. The count is the same 119.
6. Save `graph.html` and `graph.png` under `/tmp/verify-atlas-evidence/`.
7. Count `svg.graph-map a` before the page script hides the SVG. Those links are the family ids on the map.
8. If the browser can draw HTML in a canvas (Chrome for Testing 157, the binary from `scripts/install_chrome157.sh`), `svg.graph-map` is hidden after the page script runs, `a.graph-label` links are visible, and `#graph-3d` is visible. Click `#graph-3d`. Its text becomes `Flat map`, and `#graph-spin` reads `Pause rotation` (or `Resume rotation` when the browser asks for reduced motion).
9. If the browser cannot, `svg.graph-map` stays visible, `#graph-3d` stays hidden, and the edge list is still the 119 links. Record that mode. Do not treat a hidden 3D button on that browser as a broken page.

## Gotchas

- `scripts/graph_a11y_check.mjs` logs `graph a11y: drawable` or `graph a11y: fallback` during `npm run build`. CI installs Chrome for Testing `157.0.8103.15` first and fails if the mode is not drawable. A local build without that binary logs fallback, or `graph a11y: skipped: no browser` when nothing launches.
- Playwright's bundled Chromium does not set `canvas.content` to `drawable`. The 3D control stays hidden there. Use `/tmp/chrome157/chrome-linux64/chrome` to drive the drawable path.
- The page says citation edges come from OpenAI Math manuscripts only. AlphaProof, AlphaEvolve, and Anthropic rows are not nodes. AlphaEvolve rows are notebook constructions, not Lean files.
- The map sits in `.graph-scroll`. On a narrow viewport the frame scrolls sideways. The hint text is `Scroll or pinch to zoom.`
