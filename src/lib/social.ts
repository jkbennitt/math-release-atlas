import { atlas } from "./atlas";

export const SITE_NAME = "Math Release Atlas";
export const PREVIEW_IMAGE = "og.png";
export const PREVIEW_WIDTH = 1200;
export const PREVIEW_HEIGHT = 630;

// The dist check requires this sentence to match preview_alt() in scripts/atlaslib.py.
export function previewImageAlt(families: number, manuscripts: number, leanFiles: number): string {
  const catalogue = `${SITE_NAME}: ${families} result families and ${manuscripts} manuscripts from the OpenAI Math catalogue`;
  const second = leanFiles > 0 ? `, plus ${leanFiles} Lean files from AlphaProof Nexus` : "";
  return `${catalogue}${second}. Unofficial, not affiliated with OpenAI or Google DeepMind.`;
}

export function previewAltFromCatalogue(): string {
  return previewImageAlt(
    atlas.counts.families,
    atlas.counts.manuscripts,
    atlas.alphaproof.counts.lean_files,
  );
}

export function absoluteUrl(site: URL, path: string): string {
  return new URL(path, site).href;
}
