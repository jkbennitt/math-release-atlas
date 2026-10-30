export interface DrawableCanvas extends HTMLCanvasElement {
  content?: string;
  onpaint: ((event: Event) => void) | null;
  requestPaint?: () => void;
  updateElementGeometry?: (
    element: Element,
    geometry: { canvasTransform?: DOMMatrix; preserveHitTestOrder?: boolean },
  ) => void;
  clearElementGeometry?: (element: Element) => void;
  getElementImageDefaultSize?: (element: Element) => { width: number; height: number };
}

export interface Drawable2D extends CanvasRenderingContext2D {
  drawElementImage: (element: Element, dx: number, dy: number) => void;
}

export function supportsHtmlInCanvas(): boolean {
  if (typeof document === "undefined") return false;
  const canvas = document.createElement("canvas");
  canvas.setAttribute("content", "drawable");
  return (canvas as DrawableCanvas).content === "drawable";
}
