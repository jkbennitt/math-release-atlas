import {
  BufferGeometry,
  Color,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  PlaneGeometry,
  Points,
  PointsMaterial,
  Quaternion,
  Scene,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
  HTMLTexture,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { DrawableCanvas } from "./html-in-canvas";

export interface GraphEdge {
  from: string;
  to: string;
  kind: "cite" | "topic";
}

export interface Graph3dHandle {
  start(): void;
  stop(): void;
  setReducedMotion(value: boolean): void;
}

export interface Graph3dOptions {
  canvas: HTMLCanvasElement;
  labels: HTMLElement[];
  edges: GraphEdge[];
  reducedMotion: boolean;
}

interface LabelMesh {
  element: HTMLElement;
  mesh: Mesh;
}

interface CanvasPaintEvent extends Event {
  changedElements?: Element[];
}

interface UploadContext extends WebGL2RenderingContext {
  texElementSubImage2D?: (
    target: number,
    level: number,
    xoffset: number,
    yoffset: number,
    element: Element,
  ) => void;
  texElementImage2D?: (target: number, internalFormat: number, element: Element) => void;
}

const RADIUS = 8;
const SPIN = 0.16;
const bridged = new WeakSet<object>();
const corner = new Vector3();
const cameraSpace = new Vector3();
const parentSpin = new Quaternion();
const cameraSpin = new Quaternion();

function attachStableUpload(canvas: DrawableCanvas, gl: UploadContext): void {
  if (bridged.has(gl) || typeof gl.texElementSubImage2D !== "function") return;
  bridged.add(gl);
  // Three r187 uploads HTMLTexture through texElementImage2D. Chrome 157 copies
  // the element with texElementSubImage2D into storage from texImage2D.
  gl.texElementImage2D = function texElementImage2D(target, _internalFormat, element) {
    const size = canvas.getElementImageDefaultSize?.(element);
    const width = Math.max(1, Math.ceil(size?.width || element.clientWidth || 1));
    const height = Math.max(1, Math.ceil(size?.height || element.clientHeight || 1));
    this.texImage2D(
      target,
      0,
      this.RGBA8 ?? this.RGBA,
      width,
      height,
      0,
      this.RGBA,
      this.UNSIGNED_BYTE,
      null,
    );
    gl.texElementSubImage2D?.call(this, target, 0, 0, 0, element);
  };
}

function installUploadBridge(canvas: DrawableCanvas): void {
  const native = canvas.getContext.bind(canvas) as (id: string, options?: unknown) => RenderingContext | null;
  canvas.getContext = ((id: string, options?: unknown) => {
    const context = native(id, options);
    if (context && "texImage2D" in context) {
      attachStableUpload(canvas, context as UploadContext);
    }
    return context;
  }) as HTMLCanvasElement["getContext"];
}

function spherePoint(index: number, count: number): Vector3 {
  if (count <= 1) return new Vector3();
  const y = 1 - (index / (count - 1)) * 2;
  const ring = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = Math.PI * (3 - Math.sqrt(5)) * index;
  return new Vector3(Math.cos(theta) * ring, y, Math.sin(theta) * ring).multiplyScalar(RADIUS);
}

function lineGeometry(edges: GraphEdge[], at: Map<string, Vector3>, kind: GraphEdge["kind"]): BufferGeometry | null {
  const coords: number[] = [];
  for (const edge of edges) {
    if (edge.kind !== kind) continue;
    const from = at.get(edge.from);
    const to = at.get(edge.to);
    if (!from || !to) continue;
    coords.push(from.x, from.y, from.z, to.x, to.y, to.z);
  }
  if (coords.length === 0) return null;
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(coords, 3));
  return geometry;
}

function labelId(element: HTMLElement, index: number): string {
  return element.dataset.id ?? element.textContent?.trim() ?? String(index);
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

function fitLabels(labels: LabelMesh[], canvas: HTMLCanvasElement, camera: PerspectiveCamera): void {
  const visible = 2 * Math.tan((camera.fov * Math.PI) / 360) * camera.position.length();
  const worldPerPixel = visible / Math.max(canvas.clientHeight, 1);
  for (const item of labels) {
    const width = Math.max(item.element.offsetWidth, 1) * worldPerPixel;
    const height = Math.max(item.element.offsetHeight, 1) * worldPerPixel;
    item.mesh.scale.set(width, height, 1);
  }
}

function billboard(group: Group, camera: PerspectiveCamera, labels: LabelMesh[]): void {
  group.getWorldQuaternion(parentSpin);
  camera.getWorldQuaternion(cameraSpin);
  parentSpin.invert().multiply(cameraSpin);
  for (const item of labels) item.mesh.quaternion.copy(parentSpin);
}

function syncGeometry(
  canvas: DrawableCanvas,
  camera: PerspectiveCamera,
  labels: LabelMesh[],
): void {
  if (!canvas.updateElementGeometry) return;
  const ordered = labels
    .map((item) => {
      item.mesh.getWorldPosition(cameraSpace);
      cameraSpace.applyMatrix4(camera.matrixWorldInverse);
      return { item, depth: cameraSpace.z };
    })
    .sort((left, right) => left.depth - right.depth);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  for (const entry of ordered) {
    const { element, mesh } = entry.item;
    if (entry.depth >= -0.05 || element.offsetWidth < 1 || element.offsetHeight < 1) {
      canvas.clearElementGeometry?.(element);
      continue;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const lx of [-0.5, 0.5]) {
      for (const ly of [-0.5, 0.5]) {
        corner.set(lx, ly, 0).applyMatrix4(mesh.matrixWorld).project(camera);
        const x = (corner.x * 0.5 + 0.5) * width;
        const y = (-corner.y * 0.5 + 0.5) * height;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
    const boxW = maxX - minX;
    const boxH = maxY - minY;
    if (!Number.isFinite(boxW) || !Number.isFinite(boxH) || boxW < 1 || boxH < 1) {
      canvas.clearElementGeometry?.(element);
      continue;
    }
    const transform = new DOMMatrix();
    transform.a = boxW / element.offsetWidth;
    transform.d = boxH / element.offsetHeight;
    transform.e = minX;
    transform.f = minY;
    canvas.updateElementGeometry(element, { canvasTransform: transform });
  }
}

export async function mountGraph3d(options: Graph3dOptions): Promise<Graph3dHandle> {
  const canvas = options.canvas as DrawableCanvas;
  canvas.setAttribute("content", "drawable");
  canvas.content = "drawable";
  for (const label of options.labels) {
    label.setAttribute("drawable", "");
    if (label.parentElement !== canvas) canvas.appendChild(label);
  }
  await nextFrame();
  if (canvas.clientWidth < 1 || canvas.clientHeight < 1) {
    throw new Error("The 3D canvas has no size.");
  }

  installUploadBridge(canvas);
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(new Color("#faf7f1"), 1);
  const scene = new Scene();
  scene.background = new Color("#faf7f1");
  const camera = new PerspectiveCamera(45, 1, 0.1, 80);
  camera.position.set(0, 0.8, 29);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false;
  controls.minDistance = 14;
  controls.maxDistance = 40;
  controls.target.set(0, 0, 0);
  controls.enableDamping = !options.reducedMotion;
  controls.dampingFactor = 0.08;
  controls.update();

  const group = new Group();
  const positions = new Map<string, Vector3>();
  const placed = options.labels.map((element, index) => {
    const point = spherePoint(index, options.labels.length);
    positions.set(labelId(element, index), point);
    return { element, point };
  });
  const citeLines = lineGeometry(options.edges, positions, "cite");
  if (citeLines) {
    group.add(new LineSegments(citeLines, new LineBasicMaterial({ color: new Color("#1f4d4a") })));
  }
  const topicLines = lineGeometry(options.edges, positions, "topic");
  if (topicLines) {
    group.add(new LineSegments(topicLines, new LineBasicMaterial({ color: new Color("#4e483f") })));
  }
  const dotCoords: number[] = [];
  for (const point of positions.values()) dotCoords.push(point.x, point.y, point.z);
  const dots = new BufferGeometry();
  dots.setAttribute("position", new Float32BufferAttribute(dotCoords, 3));
  group.add(
    new Points(dots, new PointsMaterial({ color: new Color("#1d1a16"), size: 0.16, sizeAttenuation: true })),
  );

  const plane = new PlaneGeometry(1, 1);
  const labels: LabelMesh[] = [];
  const textures: HTMLTexture[] = [];
  for (const item of placed) {
    const texture = new HTMLTexture(item.element);
    texture.colorSpace = SRGBColorSpace;
    textures.push(texture);
    const mesh = new Mesh(plane, new MeshBasicMaterial({ map: texture, side: DoubleSide }));
    mesh.position.copy(item.point).multiplyScalar(1.14);
    group.add(mesh);
    labels.push({ element: item.element, mesh });
  }
  scene.add(group);
  fitLabels(labels, canvas, camera);

  canvas.onpaint = (event) => {
    const changed = (event as CanvasPaintEvent).changedElements;
    for (const texture of textures) {
      const image = texture.image as Element | null;
      if (!image) continue;
      if (!changed || changed.includes(image)) texture.needsUpdate = true;
    }
  };

  let reduced = options.reducedMotion;
  let running = false;
  let onScreen = true;
  let dragging = false;
  let frame = 0;
  let last = 0;

  function resize(): void {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width < 1 || height < 1) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(width, height, false);
    fitLabels(labels, canvas, camera);
  }

  function render(now: number): void {
    const delta = last === 0 ? 0 : Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!reduced && !dragging) group.rotation.y += SPIN * delta;
    if (!reduced) controls.update();
    billboard(group, camera, labels);
    group.updateMatrixWorld(true);
    syncGeometry(canvas, camera, labels);
    renderer.render(scene, camera);
  }

  function loop(now: number): void {
    frame = 0;
    if (!running) return;
    render(now);
    if (running && !reduced && onScreen && !document.hidden) {
      frame = requestAnimationFrame(loop);
    }
  }

  function kick(): void {
    if (!running || frame !== 0) return;
    last = 0;
    frame = requestAnimationFrame(loop);
  }

  const resizeObserver = new ResizeObserver(() => {
    resize();
    kick();
  });
  resizeObserver.observe(canvas);
  const visibility = new IntersectionObserver((entries) => {
    onScreen = entries.some((entry) => entry.isIntersecting);
    if (onScreen) kick();
  });
  visibility.observe(canvas);
  controls.addEventListener("start", () => {
    dragging = true;
    kick();
  });
  controls.addEventListener("end", () => {
    dragging = false;
  });
  controls.addEventListener("change", () => {
    if (reduced) kick();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) kick();
  });

  resize();
  const handle: Graph3dHandle = {
    start() {
      for (const item of labels) {
        if (item.element.parentElement !== canvas) canvas.appendChild(item.element);
      }
      running = true;
      controls.enabled = true;
      kick();
    },
    stop() {
      running = false;
      controls.enabled = false;
      if (frame !== 0) cancelAnimationFrame(frame);
      frame = 0;
      for (const item of labels) canvas.clearElementGeometry?.(item.element);
    },
    setReducedMotion(value: boolean) {
      reduced = value;
      controls.enableDamping = !value;
      if (running) kick();
    },
  };
  handle.start();
  return handle;
}
