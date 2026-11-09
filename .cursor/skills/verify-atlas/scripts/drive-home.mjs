import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const stateDir = process.env.VERIFY_ATLAS_STATE || "/tmp/verify-atlas-run";
const evidence = process.env.VERIFY_ATLAS_EVIDENCE || "/tmp/verify-atlas-evidence";
const port = (await readFile(`${stateDir}/port`, "utf8")).trim();
const home = `http://127.0.0.1:${port}/math-release-atlas/`;
const chrome = process.env.GRAPH_CHROME || "/tmp/chrome157/chrome-linux64/chrome";
const total = 373 + 71 + 18 + 5;
const counts = [
  { value: "openai-math", label: "OpenAI Math (373)", visible: 373 },
  { value: "alphaproof-nexus", label: "AlphaProof Nexus (71)", visible: 71 },
  { value: "alphaevolve", label: "AlphaEvolve (18)", visible: 18 },
  { value: "anthropic", label: "Anthropic (5)", visible: 5 },
];

function fail(message) {
  const error = new Error(message);
  error.atlas = true;
  throw error;
}

async function textOf(locator) {
  return (await locator.innerText()).replace(/\s+/g, " ").trim();
}

const notes = [];
await mkdir(evidence, { recursive: true });
const launch = { headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"] };
if (existsSync(chrome)) {
  launch.executablePath = chrome;
  notes.push(`browser ${chrome}`);
} else {
  notes.push("browser playwright-chromium");
}
const browser = await chromium.launch(launch);
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const response = await page.goto(home, { waitUntil: "networkidle", timeout: 60000 });
  if (!response || response.status() !== 200) {
    fail(`home status ${response ? response.status() : "none"}`);
  }
  await page.locator("#family-search").waitFor();
  const title = await page.title();
  if (title !== "Math Release Atlas") fail(`title ${title}`);
  for (const count of counts) {
    const option = page.locator(`#source-filter option[value="${count.value}"]`);
    const label = await textOf(option);
    if (label !== count.label) fail(`option ${count.value} is ${JSON.stringify(label)}`);
  }
  const catalogue = await textOf(page.locator("ul.catalogue"));
  if (!catalogue.includes("373 families and 721 manuscripts")) {
    fail(`catalogue missed the OpenAI count: ${catalogue}`);
  }
  if (!catalogue.includes("71 Lean files")) fail(`catalogue missed the AlphaProof count: ${catalogue}`);
  if (!catalogue.includes("18 notebook constructions")) {
    fail(`catalogue missed the AlphaEvolve count: ${catalogue}`);
  }
  if (!catalogue.includes("5 releases")) fail(`catalogue missed the Anthropic count: ${catalogue}`);
  const openaiCommitHref = await page.locator('a[href*="github.com/openai/math/commit/"]').first().getAttribute("href");
  const openaiCommit = openaiCommitHref ? openaiCommitHref.split("/commit/")[1] : "";
  if (!/^[0-9a-f]{40}$/.test(openaiCommit)) fail(`openai commit ${openaiCommitHref}`);
  await writeFile(`${evidence}/home.html`, await page.content());
  await page.screenshot({ path: `${evidence}/home.png` });
  notes.push("opened home");

  for (const count of counts) {
    await page.locator("#source-filter").selectOption(count.value);
    const shown = await textOf(page.locator("#shown-count"));
    const expected = `Showing ${count.visible} of ${total}`;
    if (shown !== expected) fail(`${count.value} shown-count is ${JSON.stringify(shown)}`);
    const visible = await page.locator(`tr[data-source="${count.value}"]:not([hidden])`).count();
    if (visible !== count.visible) fail(`${count.value} left ${visible} rows visible`);
    const others = await page.locator(`tbody tr[data-source]:not([data-source="${count.value}"]):not([hidden])`).count();
    if (others !== 0) fail(`${count.value} left ${others} other rows visible`);
    await page.screenshot({ path: `${evidence}/home-${count.value}.png` });
    notes.push(`${count.value} filter -> ${shown}`);
  }

  await page.locator("#filter-reset").click();
  const reset = await textOf(page.locator("#shown-count"));
  if (reset !== `Showing ${total} of ${total}`) fail(`reset shown-count is ${JSON.stringify(reset)}`);
  notes.push(`reset -> ${reset}`);

  await page.getByRole("link", { name: "Sources", exact: true }).click();
  await page.waitForURL(/\/math-release-atlas\/source\/$/);
  await page.getByRole("link", { name: "OpenAI Math catalogue" }).click();
  await page.waitForURL(/\/math-release-atlas\/source\/openai-math\/$/);
  const heading = await textOf(page.locator("h1"));
  if (heading !== "Manuscript catalogue") fail(`source heading ${JSON.stringify(heading)}`);
  const lead = await textOf(page.locator("p.summary-lead"));
  if (!lead.includes("373 result families and 721 manuscripts")) {
    fail(`source lead is ${JSON.stringify(lead)}`);
  }
  await writeFile(`${evidence}/source-openai.html`, await page.content());
  await page.screenshot({ path: `${evidence}/source-openai.png` });
  notes.push(`source page -> ${lead}`);

  await page.goto(`${home}source/`, { waitUntil: "networkidle", timeout: 60000 });
  await page.getByRole("link", { name: "AlphaEvolve notebook constructions" }).click();
  await page.waitForURL(/\/math-release-atlas\/source\/alphaevolve\/$/);
  const evolveHeading = await textOf(page.locator("h1"));
  if (evolveHeading !== "AlphaEvolve") fail(`alphaevolve heading ${JSON.stringify(evolveHeading)}`);
  const evolveCounts = await textOf(page.locator("#alphaevolve-counts"));
  for (const phrase of ["18 constructions.", "15 maths problems.", "19 notebooks.", "0 Lean files."]) {
    if (!evolveCounts.includes(phrase)) fail(`alphaevolve counts missed ${JSON.stringify(phrase)}: ${evolveCounts}`);
  }
  const evolveStatus = await textOf(page.locator("p.status-line").first());
  if (!evolveStatus.includes("Checked by notebook")) {
    fail(`alphaevolve status is ${JSON.stringify(evolveStatus)}`);
  }
  if (!evolveStatus.includes("This tree has no Lean files.")) {
    fail(`alphaevolve status dropped the Lean note: ${JSON.stringify(evolveStatus)}`);
  }
  await writeFile(`${evidence}/source-alphaevolve.html`, await page.content());
  await page.screenshot({ path: `${evidence}/source-alphaevolve.png` });
  notes.push(`alphaevolve -> ${evolveCounts}`);

  await page.goto(`${home}source/`, { waitUntil: "networkidle", timeout: 60000 });
  await page.getByRole("link", { name: "Anthropic releases" }).click();
  await page.waitForURL(/\/math-release-atlas\/source\/anthropic\/$/);
  const anthropicHeading = await textOf(page.locator("h1"));
  if (anthropicHeading !== "Anthropic") fail(`anthropic heading ${JSON.stringify(anthropicHeading)}`);
  const anthropicBody = await textOf(page.locator("article"));
  if (!anthropicBody.includes("FlashProve")) fail("anthropic page did not name FlashProve");
  if (!anthropicBody.includes("9e2bdd8ff5bf")) fail("anthropic page did not show the FlashProve commit");
  const anthropicCounts = await textOf(page.locator("#anthropic-counts"));
  if (!anthropicCounts.includes("flashprove: 29566 Lean files.")) {
    fail(`anthropic counts missed FlashProve: ${anthropicCounts}`);
  }
  await writeFile(`${evidence}/source-anthropic.html`, await page.content());
  await page.screenshot({ path: `${evidence}/source-anthropic.png` });
  notes.push("anthropic page names FlashProve");

  await page.goto(`${home}graph/`, { waitUntil: "networkidle", timeout: 60000 });
  await page.locator("h1").waitFor();
  const graphSvg = page.locator("svg.graph-map");
  await graphSvg.waitFor({ state: "attached" });
  const graphHeading = await textOf(page.locator("h1"));
  if (graphHeading !== "Citation graph") fail(`graph heading ${JSON.stringify(graphHeading)}`);
  const graphBody = await textOf(page.locator("article"));
  if (!graphBody.includes("119 directed links among 125 families in this catalogue.")) {
    fail(`graph sentence drifted: ${graphBody}`);
  }
  if (!graphBody.includes("AlphaEvolve") || !graphBody.includes("have no citation data")) {
    fail("graph page did not say AlphaEvolve has no citation data");
  }
  const edges = await page.locator("ul.edge-list > li").count();
  if (edges !== 119) fail(`graph listed ${edges} edges`);
  const svgHidden = await graphSvg.getAttribute("hidden");
  notes.push(svgHidden !== null ? "graph map hidden after the canvas labels draw" : "graph map stayed visible");
  await writeFile(`${evidence}/graph.html`, await page.content());
  await page.screenshot({ path: `${evidence}/graph.png` });
  notes.push(`graph -> 119 edges`);

  await page.goto(home, { waitUntil: "networkidle", timeout: 60000 });
  const familyLink = page.locator('tr#f-001 a[data-upstream="title"]');
  const familyTitle = await textOf(familyLink);
  await familyLink.click();
  await page.waitForURL(/\/math-release-atlas\/f\/001\/$/);
  const familyHeading = await textOf(page.locator('article.family h1[data-upstream="title"]'));
  if (!familyHeading || familyHeading !== familyTitle) {
    fail(`family heading ${JSON.stringify(familyHeading)} != ${JSON.stringify(familyTitle)}`);
  }
  const familyMeta = await textOf(page.locator("article.family"));
  if (!familyMeta.includes("Family 001")) fail("family page missed Family 001");
  const manuscript = page.locator("a.direct-upstream").first();
  const manuscriptHref = await manuscript.getAttribute("href");
  if (!manuscriptHref || !manuscriptHref.includes("github.com/openai/math/blob/") || !manuscriptHref.includes(openaiCommit)) {
    fail(`family manuscript href ${manuscriptHref}`);
  }
  await writeFile(`${evidence}/family-001.html`, await page.content());
  await page.screenshot({ path: `${evidence}/family-001.png` });
  notes.push(`family 001 -> ${familyHeading}`);

  const result = [
    `date ${new Date().toISOString()}`,
    `url ${home}`,
    ...notes,
    "home source overview passed",
  ].join("\n");
  await writeFile(`${evidence}/drive-result.txt`, `${result}\n`);
  console.log(result);
} catch (error) {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  await writeFile(`${evidence}/drive-result.txt`, `FAILED\n${message}\n`);
  throw error;
} finally {
  await browser.close();
}
