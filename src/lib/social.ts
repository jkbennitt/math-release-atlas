import { atlas } from "./atlas";

export const SITE_NAME = "Math Release Atlas";
export const PREVIEW_IMAGE = "og.png";
export const PREVIEW_WIDTH = 1200;
export const PREVIEW_HEIGHT = 630;

interface PreviewEntry {
  fragment: string;
  org: string;
}

// Keep this join identical to join_series() / affiliation_sentence() / preview_alt()
// in scripts/atlaslib.py. The dist check fails when the built alt text differs.
function joinSeries(items: string[], conjunction: string): string {
  if (items.length === 1) {
    return items[0];
  }
  if (items.length === 2) {
    return `${items[0]} ${conjunction} ${items[1]}`;
  }
  return `${items.slice(0, -1).join(", ")}, ${conjunction} ${items[items.length - 1]}`;
}

function affiliation(orgs: string[]): string {
  const unique: string[] = [];
  for (const org of orgs) {
    if (!unique.includes(org)) {
      unique.push(org);
    }
  }
  return `Unofficial, not affiliated with ${joinSeries(unique, "or")}.`;
}

export function previewImageAlt(entries: PreviewEntry[]): string {
  const body = entries.map((entry) => entry.fragment).join(", plus ");
  return `${SITE_NAME}: ${body}. ${affiliation(entries.map((entry) => entry.org))}`;
}

export function previewAltFromCatalogue(): string {
  return previewImageAlt(
    atlas.sources.sources.map((source) => ({
      fragment: source.preview.fragment,
      org: source.org,
    })),
  );
}

export function absoluteUrl(site: URL, path: string): string {
  return new URL(path, site).href;
}
