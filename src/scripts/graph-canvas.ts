import { supportsHtmlInCanvas, type Drawable2D, type DrawableCanvas } from "./html-in-canvas";
import type { Graph3dHandle, GraphEdge } from "./graph-3d";

type GraphView = "flat" | "space";

function readEdges(svg: SVGSVGElement): GraphEdge[] {
  const edges: GraphEdge[] = [];
  for (const line of svg.querySelectorAll("line")) {
    const from = line.dataset.from ?? "";
    const to = line.dataset.to ?? "";
    if (!from || !to) continue;
    edges.push({
      from,
      to,
      kind: line.classList.contains("topic") ? "topic" : "cite",
    });
  }
  return edges;
}

function cssColor(node: Element | null, fallback: string): string {
  if (!node) return fallback;
  const style = getComputedStyle(node);
  if (style.stroke && style.stroke !== "none") return style.stroke;
  if (style.fill && style.fill !== "none") return style.fill;
  return fallback;
}

function paintFlat(
  canvas: DrawableCanvas,
  context: Drawable2D,
  svg: SVGSVGElement,
  labels: HTMLElement[],
): void {
  const box = svg.viewBox.baseVal;
  const viewW = box.width || 1000;
  const viewH = box.height || 1000;
  const scaleX = canvas.width / viewW;
  const scaleY = canvas.height / viewH;
  const paper = getComputedStyle(svg).backgroundColor || "#faf7f1";
  const cite = cssColor(svg.querySelector("line.cite"), "#1f4d4a");
  const topic = cssColor(svg.querySelector("line.topic") ?? svg.querySelector(".topic-arrow"), "#4e483f");
  context.reset();
  context.fillStyle = paper;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.lineCap = "butt";
  const lines = [...svg.querySelectorAll("line")];
  for (const kind of ["topic", "cite"] as const) {
    context.strokeStyle = kind === "topic" ? topic : cite;
    context.fillStyle = context.strokeStyle;
    context.lineWidth = 1.25 * ((scaleX + scaleY) / 2);
    context.setLineDash(kind === "topic" ? [5 * scaleX, 4 * scaleX] : []);
    for (const line of lines) {
      const isTopic = line.classList.contains("topic");
      if (kind === "topic" ? !isTopic : isTopic) continue;
      const x1 = line.x1.baseVal.value * scaleX;
      const y1 = line.y1.baseVal.value * scaleY;
      const x2 = line.x2.baseVal.value * scaleX;
      const y2 = line.y2.baseVal.value * scaleY;
      context.beginPath();
      context.moveTo(x1, y1);
      context.lineTo(x2, y2);
      context.stroke();
      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.hypot(dx, dy) || 1;
      const ux = dx / length;
      const uy = dy / length;
      const head = 8 * ((scaleX + scaleY) / 2);
      context.beginPath();
      context.moveTo(x2, y2);
      context.lineTo(x2 - ux * head - uy * head * 0.42, y2 - uy * head + ux * head * 0.42);
      context.lineTo(x2 - ux * head + uy * head * 0.42, y2 - uy * head - ux * head * 0.42);
      context.closePath();
      context.fill();
    }
  }
  context.setLineDash([]);
  for (const label of labels) {
    if (label.parentElement !== canvas) continue;
    const id = label.dataset.id ?? "";
    const anchor = id ? svg.querySelector(`a[href$="f/${id}/"] text`) : null;
    const text = anchor instanceof SVGTextElement ? anchor : null;
    if (!text) continue;
    const size = canvas.getElementImageDefaultSize?.(label) ?? {
      width: label.offsetWidth * scaleX,
      height: label.offsetHeight * scaleY,
    };
    const x = text.x.baseVal.getItem(0).value * scaleX - size.width / 2;
    const y = text.y.baseVal.getItem(0).value * scaleY - size.height / 2;
    context.drawElementImage(label, x, y);
  }
}

function reducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function noteFor(view: GraphView, reduced: boolean): string {
  switch (view) {
    case "flat":
      return "";
    case "space":
      return reduced
        ? "The 3D view stays still. These are the same edges as the list."
        : "The 3D view turns on its own. These are the same edges as the list.";
    default: {
      const unexpected: never = view;
      return unexpected;
    }
  }
}

function buttonLabel(view: GraphView): string {
  switch (view) {
    case "flat":
      return "3D view";
    case "space":
      return "Flat map";
    default: {
      const unexpected: never = view;
      return unexpected;
    }
  }
}

export function mountGraph(): void {
  const svg = document.querySelector<SVGSVGElement>("svg.graph-map");
  const stage = document.querySelector<HTMLElement>(".graph-stage");
  const flat = document.querySelector<DrawableCanvas>("canvas.graph-canvas");
  const space = document.querySelector<DrawableCanvas>("canvas.graph-webgl");
  const button = document.querySelector<HTMLButtonElement>("#graph-3d");
  const note = document.querySelector<HTMLElement>("#graph-mode-note");
  if (!svg || !stage || !flat || !space || !button || !note) return;
  if (!supportsHtmlInCanvas()) return;
  const context = flat.getContext("2d");
  if (!context || !("drawElementImage" in context)) return;
  const draw = context as Drawable2D;
  const labels = [...flat.querySelectorAll<HTMLElement>("a.graph-label")];
  if (labels.length === 0) return;
  const edges = readEdges(svg);

  const supportsBox =
    typeof ResizeObserverEntry !== "undefined" &&
    "devicePixelContentBoxSize" in ResizeObserverEntry.prototype;
  const observer = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (!entry || flat.hidden) return;
    const cssW = entry.contentRect.width;
    const cssH = entry.contentRect.height;
    if (cssW < 1 || cssH < 1) return;
    const box = entry.devicePixelContentBoxSize;
    const nextW = box ? box[0].inlineSize : Math.round(cssW * window.devicePixelRatio);
    const nextH = box ? box[0].blockSize : Math.round(cssH * window.devicePixelRatio);
    if (flat.width !== nextW || flat.height !== nextH) {
      flat.width = nextW;
      flat.height = nextH;
    }
    flat.requestPaint?.();
  });

  flat.addEventListener("paint", () => {
    if (flat.hidden || flat.width < 1 || flat.height < 1) return;
    paintFlat(flat, draw, svg, labels);
  });

  let view: GraphView = "flat";
  let session: Graph3dHandle | null = null;
  let opening = false;

  function showNote(): void {
    note.textContent = noteFor(view, reducedMotion());
  }

  function showFlat(): void {
    view = "flat";
    session?.stop();
    for (const label of labels) {
      if (label.parentElement !== flat) flat.appendChild(label);
    }
    space.hidden = true;
    stage.classList.add("is-live");
    svg.hidden = true;
    flat.hidden = false;
    button.hidden = false;
    button.setAttribute("aria-pressed", "false");
    button.textContent = buttonLabel("flat");
    showNote();
    observer.observe(flat, supportsBox ? { box: "device-pixel-content-box" } : undefined);
    flat.requestPaint?.();
  }

  async function showSpace(): Promise<void> {
    if (opening) return;
    opening = true;
    button.disabled = true;
    try {
      // Three.js stays in this chunk so browsers without the drawable canvas do not fetch it.
      const mod = await import("./graph-3d");
      for (const label of labels) {
        label.style.fontSize = "";
        if (label.parentElement !== space) space.appendChild(label);
      }
      flat.hidden = true;
      space.hidden = false;
      stage.classList.add("is-live");
      svg.hidden = true;
      if (!session) {
        session = await mod.mountGraph3d({
          canvas: space,
          labels,
          edges,
          reducedMotion: reducedMotion(),
        });
      } else {
        session.setReducedMotion(reducedMotion());
        session.start();
      }
      view = "space";
      button.setAttribute("aria-pressed", "true");
      button.textContent = buttonLabel("space");
      showNote();
    } catch {
      for (const label of labels) {
        if (label.parentElement !== flat) flat.appendChild(label);
      }
      space.hidden = true;
      flat.hidden = false;
      view = "flat";
      button.textContent = buttonLabel("flat");
      button.setAttribute("aria-pressed", "false");
      note.textContent = "The 3D view did not open in this browser. The flat map is showing.";
      flat.requestPaint?.();
    } finally {
      button.disabled = false;
      opening = false;
    }
  }

  button.addEventListener("click", () => {
    if (view === "flat") {
      void showSpace();
      return;
    }
    showFlat();
  });

  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  motion.addEventListener("change", () => {
    session?.setReducedMotion(motion.matches);
    if (view === "space") showNote();
  });

  showFlat();
}
