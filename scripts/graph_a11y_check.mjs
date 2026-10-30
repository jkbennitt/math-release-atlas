import { createServer } from "node:http";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { chromium } from "playwright";

const dist = process.argv[2];
const expected = Number(process.argv[3]);
if (!dist || !Number.isInteger(expected) || expected < 1) {
  console.error("usage: node scripts/graph_a11y_check.mjs dist EXPECTED");
  process.exit(2);
}

const BASE = "/math-release-atlas";
const MAP_LABEL = "Map of the citation edges listed below.";
const CHROME_157 = process.env.GRAPH_CHROME || "/tmp/chrome157/chrome-linux64/chrome";
const failures = [];

function fail(message) {
  failures.push(message);
}

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json",
  ".woff2": "font/woff2",
};

function startServer(root) {
  const rootPath = normalize(root);
  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      const pathname = decodeURIComponent(url.pathname);
      if (!pathname.startsWith(BASE)) {
        response.writeHead(404);
        response.end("not found");
        return;
      }
      let relative = pathname.slice(BASE.length) || "/";
      if (relative.endsWith("/")) relative += "index.html";
      const file = normalize(join(rootPath, relative));
      if (!file.startsWith(rootPath)) {
        response.writeHead(403);
        response.end("forbidden");
        return;
      }
      const body = await readFile(file);
      const type = TYPES[extname(file)] ?? "application/octet-stream";
      response.writeHead(200, { "content-type": type });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end("not found");
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        throw new Error("graph a11y server has no port");
      }
      resolve({ server, port: address.port });
    });
  });
}

function inCi() {
  return process.env.CI === "true" || process.env.GITHUB_ACTIONS === "true";
}

async function launchBrowser() {
  const args = ["--no-sandbox", "--disable-dev-shm-usage"];
  const errors = [];
  if (existsSync(CHROME_157)) {
    try {
      return {
        browser: await chromium.launch({ executablePath: CHROME_157, headless: true, args }),
        expectDrawable: true,
      };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }
  try {
    return {
      browser: await chromium.launch({ channel: "chrome", headless: true, args }),
      expectDrawable: false,
    };
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
  try {
    return {
      browser: await chromium.launch({ headless: true, args }),
      expectDrawable: false,
    };
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
  if (inCi()) {
    console.error(`graph a11y: no browser launched\n${errors.join("\n")}`);
    process.exit(1);
  }
  console.log("graph a11y: skipped: no browser");
  return null;
}

async function focusState(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    return {
      id: el?.id ?? "",
      label: el?.classList?.contains("graph-label") ?? false,
      svg: !!el?.closest("svg.graph-map"),
      canvas: el?.closest("canvas")?.className ?? "",
      text: (el?.textContent ?? "").trim(),
    };
  });
}

async function exposedLinks(page) {
  return page.evaluate(() => {
    const links = [...document.querySelectorAll(".graph-stage a")];
    return links
      .filter((link) => {
        for (let node = link; node; node = node.parentElement) {
          if (node.hasAttribute("hidden")) return false;
          const style = getComputedStyle(node);
          if (style.display === "none" || style.visibility === "hidden") return false;
        }
        return true;
      })
      .map((link) => ({
        text: (link.textContent ?? "").trim(),
        label: link.classList.contains("graph-label"),
        svg: !!link.closest("svg.graph-map"),
        canvas: link.closest("canvas")?.className ?? "",
      }));
  });
}

async function assertMapLabel(page) {
  const label = await page.locator("canvas.graph-canvas").getAttribute("aria-label");
  const webgl = await page.locator("canvas.graph-webgl").getAttribute("aria-label");
  if (label !== MAP_LABEL || webgl !== MAP_LABEL) {
    fail(`canvas aria-label is ${JSON.stringify(label)} / ${JSON.stringify(webgl)}`);
  }
}

async function assertExposed(page, mode) {
  const roleCount = await page.locator(".graph-stage").getByRole("link").count();
  const exposed = await exposedLinks(page);
  if (roleCount !== expected) {
    fail(`${mode}: accessibility tree exposes ${roleCount} map links, expected ${expected}`);
  }
  if (exposed.length !== expected) {
    fail(`${mode}: ${exposed.length} map links are visible, expected ${expected}`);
  }
  return exposed;
}

async function walkTabs(page, steps, check) {
  const seen = [];
  for (let index = 0; index < steps; index += 1) {
    await page.keyboard.press("Tab");
    const state = await focusState(page);
    seen.push(state);
    const problem = check(state, index);
    if (problem) {
      fail(problem);
      return seen;
    }
  }
  return seen;
}

async function checkDrawable(page) {
  await page.waitForFunction(() => {
    const svg = document.querySelector("svg.graph-map");
    const label = document.querySelector("canvas.graph-canvas a.graph-label");
    const box = label?.getBoundingClientRect();
    return !!svg?.hasAttribute("hidden") && !!box && box.width > 0 && box.height > 0;
  });
  const hiddenDisplay = await page.evaluate(() => getComputedStyle(document.querySelector("svg.graph-map")).display);
  if (hiddenDisplay !== "none") {
    fail(`drawable: svg display is ${hiddenDisplay}`);
  }
  const spinHidden = await page.locator("#graph-spin").getAttribute("hidden");
  if (spinHidden === null) fail("drawable: pause control is visible on the flat map");
  const exposed = await assertExposed(page, "drawable");
  if (exposed.some((link) => !link.label || link.svg || !link.canvas.includes("graph-canvas"))) {
    fail("drawable: an exposed map link is not a canvas family label");
  }
  await page.locator("#graph-3d").focus();
  const tabs = await walkTabs(page, expected, (state) => {
    if (!state.label || state.svg || !state.canvas.includes("graph-canvas")) {
      return `drawable: tab landed on ${state.text || state.id || "an unnamed control"} instead of a canvas label`;
    }
    return "";
  });
  const names = new Set(tabs.map((state) => state.text));
  if (names.size !== expected) {
    fail(`drawable: tab order visited ${names.size} family labels, expected ${expected}`);
  }
  await page.keyboard.press("Tab");
  const after = await focusState(page);
  if (after.label || after.svg) {
    fail(`drawable: tab left the labels onto another map link (${after.text})`);
  }

  await page.locator("#graph-3d").click();
  await page.waitForFunction(() => document.querySelector("#graph-3d")?.textContent?.includes("Flat map"));
  await page.locator("#graph-spin").focus();
  const spinFocus = await focusState(page);
  if (spinFocus.id !== "graph-spin") fail("drawable: pause control is not keyboard reachable");
  const spinText = (await page.locator("#graph-spin").innerText()).trim();
  if (spinText !== "Pause rotation") fail(`drawable: pause control reads ${JSON.stringify(spinText)}`);
  await page.locator("#graph-spin").click();
  const pausedText = (await page.locator("#graph-spin").innerText()).trim();
  if (pausedText !== "Resume rotation") fail(`drawable: after pause the control reads ${JSON.stringify(pausedText)}`);

  await page.setViewportSize({ width: 390, height: 800 });
  await page.waitForTimeout(200);
  const frame = await page.evaluate(() => {
    const canvas = document.querySelector("canvas.graph-webgl");
    const stage = document.querySelector(".graph-stage");
    const canvasBox = canvas.getBoundingClientRect();
    const stageBox = stage.getBoundingClientRect();
    return {
      touch: getComputedStyle(canvas).touchAction,
      canvasH: canvasBox.height,
      stageH: stageBox.height,
      innerH: window.innerHeight,
      scrollH: document.documentElement.scrollHeight,
    };
  });
  if (frame.touch !== "pan-y") fail(`drawable: 3D touch-action is ${frame.touch}`);
  const cap = frame.innerH * 0.8 + 2;
  if (frame.canvasH > cap) fail(`drawable: 3D canvas is ${frame.canvasH}px, above 80vh`);
  if (frame.stageH > cap) fail(`drawable: 3D stage is ${frame.stageH}px, above 80vh`);
  if (frame.scrollH <= frame.innerH) fail("drawable: the page cannot scroll past the 3D view");
  const webgl = page.locator("canvas.graph-webgl");
  await webgl.scrollIntoViewIfNeeded();
  const box = await webgl.boundingBox();
  if (!box) {
    fail("drawable: 3D canvas has no box");
  } else {
    const before = await page.evaluate(() => window.scrollY);
    await page.mouse.move(box.x + Math.min(24, box.width / 2), box.y + Math.min(24, box.height / 2));
    await page.mouse.wheel(0, 600);
    await page.waitForTimeout(100);
    const after = await page.evaluate(() => window.scrollY);
    if (after < before + 40) {
      fail(`drawable: wheel over the 3D view did not scroll the page (${before} to ${after})`);
    }
  }
}

async function checkReduced(browser, url) {
  const page = await browser.newPage({
    viewport: { width: 1100, height: 900 },
    reducedMotion: "reduce",
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.locator("#graph-3d").click();
  await page.waitForFunction(() => document.querySelector("#graph-3d")?.textContent?.includes("Flat map"));
  const text = (await page.locator("#graph-spin").innerText()).trim();
  const pressed = await page.locator("#graph-spin").getAttribute("aria-pressed");
  if (text !== "Resume rotation" || pressed !== "true") {
    fail(`reduced motion starts the 3D view as ${JSON.stringify(text)} pressed=${pressed}`);
  }
  await page.locator("#graph-spin").focus();
  const active = await page.evaluate(() => document.activeElement?.id ?? "");
  if (active !== "graph-spin") fail("reduced motion: pause control is not keyboard reachable");
  if (errors.length) fail(`reduced motion page error: ${errors.join("; ")}`);
  await page.close();
}

async function checkFallback(page) {
  const state = await page.evaluate(() => {
    const svg = document.querySelector("svg.graph-map");
    const button = document.querySelector("#graph-3d");
    const spin = document.querySelector("#graph-spin");
    const canvas = document.querySelector("canvas.graph-canvas");
    return {
      svgHidden: svg?.hasAttribute("hidden") ?? false,
      display: svg ? getComputedStyle(svg).display : "",
      buttonHidden: button?.hidden ?? false,
      spinHidden: spin?.hidden ?? false,
      canvasHidden: canvas?.hidden ?? false,
    };
  });
  if (state.svgHidden || state.display === "none") fail("fallback: the SVG map is hidden");
  if (!state.buttonHidden || !state.spinHidden || !state.canvasHidden) {
    fail("fallback: a canvas control is visible");
  }
  const exposed = await assertExposed(page, "fallback");
  if (exposed.some((link) => link.label || !link.svg)) {
    fail("fallback: an exposed map link is not an SVG family link");
  }
  await page.locator("svg.graph-map a").first().focus();
  await walkTabs(page, expected - 1, (state) => {
    if (!state.svg || state.label) {
      return `fallback: tab landed outside the SVG map (${state.text || state.id})`;
    }
    return "";
  });
  await page.keyboard.press("Tab");
  const after = await focusState(page);
  if (after.svg || after.label) fail("fallback: tab stayed on a map link after the family labels");
}

const { server, port } = await startServer(dist);
const launched = await launchBrowser();
if (!launched) {
  server.close();
  process.exit(0);
}
const { browser, expectDrawable } = launched;
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1600 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const url = `http://127.0.0.1:${port}${BASE}/graph/`;
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(300);
  const labelCount = await page.locator("canvas.graph-canvas a.graph-label").count();
  if (labelCount !== expected) {
    fail(`canvas.graph-canvas a.graph-label is ${labelCount}, catalogue has ${expected}`);
  }
  const drawable = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.setAttribute("content", "drawable");
    return canvas.content === "drawable";
  });
  if (expectDrawable && !drawable) {
    fail("Chrome 157 was launched and canvas.content is not drawable");
  }
  const mode = drawable ? "drawable" : "fallback";
  console.log(`graph a11y: ${mode}`);
  await assertMapLabel(page);
  if (drawable) {
    await checkDrawable(page);
    await checkReduced(browser, url);
  } else {
    await checkFallback(page);
  }
  if (errors.length) fail(`page error: ${errors.join("; ")}`);
} finally {
  await browser.close();
  server.close();
}

if (failures.length) {
  for (const message of failures) console.error(message);
  process.exit(1);
}
