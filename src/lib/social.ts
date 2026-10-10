import { atlas } from "./atlas";

export const SITE_NAME = "Math Release Atlas";
export const PREVIEW_IMAGE = "og.png";
export const PREVIEW_WIDTH = 1200;
export const PREVIEW_HEIGHT = 630;

// The dist check requires this sentence to match preview_alt() in scripts/atlaslib.py.
export function previewImageAlt(families: number, manuscripts: number): string {
  return `${SITE_NAME}: ${families} result families and ${manuscripts} manuscripts. Unofficial.`;
}

export function previewAltFromCatalogue(): string {
  return previewImageAlt(atlas.counts.families, atlas.counts.manuscripts);
}

export function absoluteUrl(site: URL, path: string): string {
  return new URL(path, site).href;
}
