import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const stateDir = process.env.VERIFY_ATLAS_STATE || "/tmp/verify-atlas-run";
const evidence = process.env.VERIFY_ATLAS_EVIDENCE || "/tmp/verify-atlas-evidence";
const port = (await readFile(`${stateDir}/port`, "utf8")).trim();
const home = `http://127.0.0.1:${port}/math-release-atlas/`;
const chrome = process.env.GRAPH_CHROME || "/tmp/chrome157/chrome-linux64/chrome";
const total = 373 + 71 + 4;
const counts = [
  { value: "openai-math", label: "OpenAI Math (373)", visible: 373 },
  { value: "alphaproof-nexus", label: "AlphaProof Nexus (71)", visible: 71 },
  { value: "anthropic", label: "Anthropic (4)", visible: 4 },
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
  if (!catalogue.includes("4 releases")) fail(`catalogue missed the Anthropic count: ${catalogue}`);
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
