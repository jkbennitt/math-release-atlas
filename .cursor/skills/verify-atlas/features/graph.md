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

Open `http://127.0.0.1:4321/math-release-atlas/graph/` and wait for `svg.graph-map`.

1. Read `h1`. It is `Citation graph`.
2. Read the paragraph that contains `directed links among`. At this catalogue it is `119 directed links among 125 families in this catalogue.`
3. Count `ul.edge-list > li`. The count is the same 119.
4. Count `svg.graph-map a`. Those links are the family ids on the map.
5. If the browser can draw HTML in a canvas (Chrome for Testing 157, the binary from `scripts/install_chrome157.sh`), `svg.graph-map` is hidden after the page script runs, `a.graph-label` links are visible, and `#graph-3d` is visible. Click `#graph-3d`. Its text becomes `Flat map`, and `#graph-spin` reads `Pause rotation` (or `Resume rotation` when the browser asks for reduced motion).
6. If the browser cannot, `svg.graph-map` stays visible, `#graph-3d` stays hidden, and the edge list is still the 119 links. Record that mode. Do not treat a hidden 3D button on that browser as a broken page.

Save the HTML, a screenshot, and the mode you observed under `/tmp/verify-atlas-evidence/`.

## Gotchas

- `scripts/graph_a11y_check.mjs` logs `graph a11y: drawable` or `graph a11y: fallback` during `npm run build`. CI installs Chrome for Testing `157.0.8103.15` first and fails if the mode is not drawable. A local build without that binary logs fallback, or `graph a11y: skipped: no browser` when nothing launches.
- Playwright's bundled Chromium does not set `canvas.content` to `drawable`. The 3D control stays hidden there. Use `/tmp/chrome157/chrome-linux64/chrome` to drive the drawable path.
- The page says citation edges come from OpenAI Math manuscripts only. AlphaProof and Anthropic rows are not nodes.
- The map sits in `.graph-scroll`. On a narrow viewport the frame scrolls sideways. The hint text is `Scroll or pinch to zoom.`
