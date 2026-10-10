import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { chromium } from "playwright";

const dist = process.argv[2];
if (!dist) {
  console.error("usage: node scripts/layout_check.mjs dist");
  process.exit(2);
}

const BASE = "/math-release-atlas";
const VIEWPORT_WIDTH = 1024;
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
    };
  });
}

function layoutFailures(label, metrics) {
  const failures = [];
  if (metrics.pageOverflow > 1) {
    failures.push(`${label}: home page overflows horizontally by ${metrics.pageOverflow}px`);
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
  return failures;
}

const introPattern =
  /Formalization scope: .+ Generated \d{4}-\d{2}-\d{2} from [0-9a-f]{12}\. Overview PDF · Manuscript map · Citation graph/;

const { server, port } = await startServer(dist);
const failures = [];
let browser;
try {
  browser = await launchChrome();
  const page = await browser.newPage({ viewport: { width: VIEWPORT_WIDTH, height: 900 } });
  const response = await page.goto(`http://127.0.0.1:${port}${BASE}/`, { waitUntil: "networkidle" });
  if (response === null || !response.ok()) {
    failures.push(`home page did not load (${response?.status() ?? "no response"})`);
  } else {
    await page.locator("[data-family-table]").waitFor();
    const intro = (await page.locator("p.provenance").innerText()).replace(/\s+/g, " ").trim();
    if (!introPattern.test(intro) || /progress\.Generated|from[0-9a-f]|PDF·|map·/.test(intro)) {
      failures.push(`snapshot intro runs together: ${intro}`);
    }
    failures.push(...layoutFailures("1024px", await measure(page)));
    await page.evaluate(() => {
      for (const item of document.querySelectorAll("details")) {
        item.open = true;
      }
    });
    failures.push(...layoutFailures("1024px with disclosures open", await measure(page)));
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
