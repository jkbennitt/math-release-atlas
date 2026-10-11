import { createServer } from "node:http";
import { readdirSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { chromium } from "playwright";

const dist = process.argv[2];
if (!dist) {
  console.error("usage: node scripts/layout_check.mjs dist");
  process.exit(2);
}

const BASE = "/math-release-atlas";
const WIDTHS = [1024, 390];

function lensTagPages() {
  const root = join(dist, "lens");
  let names = [];
  try {
    names = readdirSync(root, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    names = [];
  }
  return names.map((name) => ({ path: `/lens/${name}/`, name: `lens-${name}` }));
}

const lensRoutes = lensTagPages();
if (lensRoutes.length === 0) {
  console.error("layout check found no lens tag pages");
  process.exit(1);
}

const PAGES = [
  { path: "/", name: "home" },
  { path: "/source/", name: "source" },
  { path: "/source/alphaproof-nexus/", name: "alphaproof" },
  { path: "/source/anthropic/", name: "anthropic" },
  { path: "/source/cross/", name: "cross" },
  { path: "/about/", name: "about" },
  { path: "/status/", name: "status" },
  { path: "/f/001/", name: "family-001" },
  { path: "/lens/", name: "lenses" },
  ...lensRoutes,
  { path: "/graph/", name: "graph" },
];
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
      if (relative.endsWith("/")) {
        relative += "index.html";
      }
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
        throw new Error("layout check server has no port");
      }
      resolve({ server, port: address.port });
    });
  });
}

async function launchChrome() {
  const args = ["--no-sandbox", "--disable-dev-shm-usage"];
  try {
    return await chromium.launch({ channel: "chrome", args });
  } catch (error) {
    const candidates = [
      process.env.CHROME_PATH,
      "/usr/bin/google-chrome",
      "/usr/bin/google-chrome-stable",
      "/usr/local/bin/google-chrome",
    ].filter((item) => item);
    for (const executablePath of candidates) {
      try {
        return await chromium.launch({ executablePath, args });
      } catch {
        // Try the next installed binary.
      }
    }
    throw error;
  }
}

async function measure(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const table = document.querySelector("[data-family-table]");
    const scroller = document.querySelector(".table-scroll");
    const caption = table?.querySelector("caption") ?? null;
    const idCell = table?.querySelector("tbody td.id") ?? null;
    const resultCell = table?.querySelector("tbody tr td:nth-child(3)") ?? null;
    const idBox = idCell?.getBoundingClientRect();
    const resultBox = resultCell?.getBoundingClientRect();
    const headers = table === null ? [] : [...table.querySelectorAll("thead th")].map((cell) => {
      const button = cell.querySelector("button");
      const target = button ?? cell;
      const range = document.createRange();
      range.selectNodeContents(target);
      const cellBox = cell.getBoundingClientRect();
      const textBox = target.getBoundingClientRect();
      return {
        text: (target.textContent ?? "").trim(),
        lines: range.getClientRects().length,
        overflow: textBox.right - cellBox.right,
      };
    });
    return {
      pageOverflow: root.scrollWidth - root.clientWidth,
      scrollerOverflow: scroller === null ? -1 : scroller.scrollWidth - scroller.clientWidth,
      captionOverflow: caption === null ? -1 : caption.scrollWidth - caption.clientWidth,
      captionText: caption?.textContent ?? "",
      resultOverflow: resultCell === null ? -1 : resultCell.scrollWidth - resultCell.clientWidth,
      idWidth: idBox?.width ?? 0,
      resultWidth: resultBox?.width ?? 0,
      resultRight: resultBox?.right ?? 0,
      clientWidth: root.clientWidth,
      headers,
    };
  });
}

function channel(value) {
  const part = value / 255;
  return part <= 0.04045 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4;
}

function luminance(color) {
  return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2]);
}

function contrast(left, right) {
  const lighter = Math.max(luminance(left), luminance(right));
  const darker = Math.min(luminance(left), luminance(right));
  return (lighter + 0.05) / (darker + 0.05);
}

function parseColor(value) {
  const match = String(value).match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/);
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

async function readGraphMap(page) {
  return page.evaluate(() => {
    const map = document.querySelector("svg.graph-map");
    const hint = document.querySelector(".map-hint");
    const list = document.querySelector(".edge-list");
    const body = document.body.textContent ?? "";
    if (map === null) {
      return { missing: true, hiddenSentence: body.includes("diagram is hidden") };
    }
    const style = getComputedStyle(map);
    const paint = (node) => {
      if (node === null) {
        return "";
      }
      const painted = getComputedStyle(node);
      if (painted.stroke && painted.stroke !== "none") {
        return painted.stroke;
      }
      return painted.fill;
    };
    const cite = map.querySelector("line.cite");
    const topic = map.querySelector("line.topic") ?? map.querySelector(".topic-arrow");
    const label = map.querySelector("text");
    const box = map.getBoundingClientRect();
    return {
      missing: false,
      display: style.display,
      visibility: style.visibility,
      width: box.width,
      height: box.height,
      background: style.backgroundColor,
      cite: paint(cite),
      topic: paint(topic),
      label: paint(label),
      hintDisplay: hint === null ? "" : getComputedStyle(hint).display,
      hintText: hint === null ? "" : (hint.textContent ?? "").trim(),
      hasList: list !== null,
      hiddenSentence: body.includes("diagram is hidden"),
    };
  });
}

function graphMapFailures(label, map, width) {
  const failures = [];
  if (map.missing) {
    failures.push(`${label}: citation map is missing`);
    return failures;
  }
  if (map.display === "none" || map.visibility === "hidden") {
    failures.push(`${label}: citation map is hidden (${map.display}, ${map.visibility})`);
  }
  if (map.width < 1 || map.height < 1) {
    failures.push(`${label}: citation map is ${map.width} by ${map.height}`);
  }
  if (width === 390 && map.width < 640) {
    failures.push(`${label}: citation map is ${map.width.toFixed(1)}px wide`);
  }
  if (map.hiddenSentence) {
    failures.push(`${label}: the narrow-screen hide sentence is still on the page`);
  }
  if (width === 390 && (map.hintDisplay === "none" || map.hintText !== "Scroll or pinch to zoom.")) {
    failures.push(`${label}: scroll hint is missing`);
  }
  if (!map.hasList) {
    failures.push(`${label}: citation edge list is missing`);
  }
  const paper = parseColor(map.background);
  if (paper === null) {
    failures.push(`${label}: map background ${map.background} could not be read`);
  } else {
    for (const [name, raw] of [
      ["cite line", map.cite],
      ["topic line", map.topic],
      ["label", map.label],
    ]) {
      const color = parseColor(raw);
      if (color === null) {
        failures.push(`${label}: ${name} color ${raw} could not be read`);
        continue;
      }
      const ratio = contrast(color, paper);
      if (ratio < 3) {
        failures.push(`${label}: ${name} is ${ratio.toFixed(2)}:1 on the map`);
      }
    }
  }
  return failures;
}

function layoutFailures(label, metrics, table) {
  const failures = [];
  if (metrics.pageOverflow > 1) {
    failures.push(`${label}: page overflows horizontally by ${metrics.pageOverflow}px`);
  }
  if (!table) {
    return failures;
  }
  if (metrics.scrollerOverflow > 1) {
    failures.push(`${label}: home table overflows its container by ${metrics.scrollerOverflow}px`);
  }
  if (metrics.captionOverflow > 1 || !metrics.captionText.includes("catalogue order, with upstream links")) {
    failures.push(`${label}: table caption is clipped or missing`);
  }
  if (metrics.resultOverflow > 1 || metrics.resultRight > metrics.clientWidth + 1) {
    failures.push(`${label}: result column is cut off`);
  }
  if (metrics.idWidth <= 0 || metrics.idWidth >= metrics.resultWidth || metrics.idWidth > 140) {
    failures.push(
      `${label}: ID column is ${Math.round(metrics.idWidth)}px and result is ${Math.round(metrics.resultWidth)}px`,
    );
  }
  for (const header of metrics.headers) {
    if (header.lines > 1) {
      failures.push(`${label}: ${header.text} header wraps onto ${header.lines} lines`);
    }
    if (header.overflow > 1) {
      failures.push(
        `${label}: ${header.text} header overflows its cell by ${Math.round(header.overflow)}px`,
      );
    }
  }
  return failures;
}

const introPattern =
  /Formalization scope: .+ Generated \d{4}-\d{2}-\d{2} from [0-9a-f]{12}\. Overview PDF · Manuscript map · Citation graph/;

const { server, port } = await startServer(dist);
const failures = [];
let browser;
try {
  browser = await launchChrome();
  const page = await browser.newPage({ viewport: { width: WIDTHS[0], height: 900 } });
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of PAGES) {
      const label = `${route.name} at ${width}px`;
      const response = await page.goto(`http://127.0.0.1:${port}${BASE}${route.path}`, {
        waitUntil: "networkidle",
      });
      if (response === null || !response.ok()) {
        failures.push(`${label} did not load (${response?.status() ?? "no response"})`);
        continue;
      }
      const home = route.name === "home";
      if (home && width === 390) {
        const barHeights = await page.evaluate(() =>
          [...document.querySelectorAll(".share-bar")].map((node) => node.getBoundingClientRect().height),
        );
        if (barHeights.length === 0) {
          failures.push("home at 390px: share bars are missing");
        }
        for (const height of barHeights) {
          if (height < 10) {
            failures.push(`home at 390px: share bar is ${height.toFixed(1)}px`);
          }
        }
      }
      if (home) {
        await page.locator("[data-family-table]").waitFor();
        if (width === 1024) {
          const intro = (await page.locator("p.provenance").innerText()).replace(/\s+/g, " ").trim();
          if (!introPattern.test(intro) || /progress\.Generated|from[0-9a-f]|PDF·|map·/.test(intro)) {
            failures.push(`snapshot intro runs together: ${intro}`);
          }
        }
      }
      if (route.name === "graph") {
        failures.push(...graphMapFailures(label, await readGraphMap(page), width));
        if (width === 390) {
          await page.emulateMedia({ colorScheme: "dark" });
          failures.push(...graphMapFailures(`${label} dark`, await readGraphMap(page), width));
          await page.emulateMedia({ colorScheme: "light" });
        }
      }
      failures.push(...layoutFailures(label, await measure(page), home && width === 1024));
      if (home) {
        await page.evaluate(() => {
          for (const item of document.querySelectorAll("details")) {
            item.open = true;
          }
        });
        failures.push(
          ...layoutFailures(`${label} with disclosures open`, await measure(page), width === 1024),
        );
      }
    }
  }
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  failures.push(`home layout check could not run: ${message}`);
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}

if (failures.length > 0) {
  console.error(failures.join("\n"));
  process.exit(1);
}
