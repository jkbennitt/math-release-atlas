import { atlas } from "./atlas";

export const SITE_NAME = "Math Release Atlas";
export const PREVIEW_IMAGE = "og.png";
export const PREVIEW_WIDTH = 1200;
export const PREVIEW_HEIGHT = 630;
const PREVIEW_ALT_MAX = 300;
const FORMALIZATION_NOTE = "Fermat's Last Theorem: Formalization, not a new result";

interface PreviewTile {
  value: string;
  label: string;
}

interface PreviewEntry {
  name: string;
  org: string;
  fragment: string;
  detail: string;
  tiles: PreviewTile[];
}

// Keep this sentence identical to preview_alt() in scripts/atlaslib.py.
// The dist check fails when the built alt text differs.
const GAP_STATUS =
  /,\s*(?:OEIS \d+ of \d+ in paper \([^)]*\)|attempted list [^,]+|per-row provenance [^,]+)/g;

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

function formalizationNote(entry: PreviewEntry): string {
  if (entry.fragment.includes(FORMALIZATION_NOTE) || entry.detail.includes(FORMALIZATION_NOTE)) {
    return FORMALIZATION_NOTE;
  }
  return "";
}

function countPhrases(entry: PreviewEntry, compact: boolean): string[] {
  const phrases: string[] = [];
  for (const tile of entry.tiles) {
    if (!/^\d+$/.test(tile.value) || !tile.label) {
      continue;
    }
    const label = compact && tile.label === "result families" ? "families" : tile.label;
    phrases.push(`${tile.value} ${label}`);
  }
  return phrases;
}

function fragmentClause(entry: PreviewEntry, compact: boolean): string {
  let fragment = entry.fragment.replace(GAP_STATUS, "").split(FORMALIZATION_NOTE).join("");
  if (compact) {
    fragment = fragment.split(" result families").join(" families");
  }
  return fragment.replace(/\s{2,}/g, " ").replace(/^[\s.,]+|[\s.,]+$/g, "");
}

function previewClause(entry: PreviewEntry, compact: boolean): string {
  const phrases = countPhrases(entry, compact);
  if (phrases.length > 0 && entry.name) {
    const [lead, ...rest] = phrases;
    if (rest.length > 0 && formalizationNote(entry)) {
      return `${entry.name}: ${lead} (${rest.join(", ")})`;
    }
    if (rest.length > 0) {
      return `${entry.name}: ${lead}, ${rest.join(", ")}`;
    }
    return `${entry.name}: ${lead}`;
  }
  return fragmentClause(entry, compact);
}

function assemblePreviewAlt(entries: PreviewEntry[], compact: boolean): string {
  const body = entries
    .map((entry) => previewClause(entry, compact))
    .filter((clause) => clause)
    .join(". ");
  const note = entries.map((entry) => formalizationNote(entry)).find((item) => item) ?? "";
  const line = affiliation(entries.map((entry) => entry.org));
  if (note) {
    return `${SITE_NAME}: ${body}. ${note}. ${line}`;
  }
  return `${SITE_NAME}: ${body}. ${line}`;
}

export function previewImageAlt(entries: PreviewEntry[]): string {
  const sentence = assemblePreviewAlt(entries, false);
  if (sentence.length <= PREVIEW_ALT_MAX) {
    return sentence;
  }
  return assemblePreviewAlt(entries, true);
}

export function previewAltFromCatalogue(): string {
  return previewImageAlt(
    atlas.sources.sources.map((source) => ({
      name: source.name,
      org: source.org,
      fragment: source.preview.fragment,
      detail: source.preview.detail,
      tiles: source.preview.tiles,
    })),
  );
}

export function absoluteUrl(site: URL, path: string): string {
  return new URL(path, site).href;
}
