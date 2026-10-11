import { atlas } from "./atlas";
import type { Family } from "./atlas";
import type { LeanStatus } from "./lean";

export const SITE_NAME = "Math Release Atlas";
export const PREVIEW_IMAGE = "og.png";
export const PREVIEW_WIDTH = 1200;
export const PREVIEW_HEIGHT = 630;

// Keep this sentence identical to card_alt() in scripts/og_card.py.
// The dist check fails when the built alt text differs.
const SOCIAL_IMAGE_ALT_MAX = 420;
const FORMALIZATION_NOTE = "Fermat's Last Theorem: Formalization, not a new result";
const HEADLINE = "AI math claims: on paper, or in Lean?";
const SHARE_LABEL = "Share with Lean files";
const LEAN_MAIN = "main-result-formalized";
const LEAN_CHALLENGE = "comparator-challenge-only";
const LEAN_NONE = "none";
const KIND_NEW = "new-result";
const KIND_FORMALIZATION = "formalization";

interface ShareGap {
  id?: string;
  absent?: number;
}

interface ShareRelease {
  kind?: string;
  title?: string;
  counts?: { lean_files?: number };
}

interface ShareBlock {
  source?: { id?: string };
  counts?: {
    lean_files?: number;
    releases?: number;
    new_results?: number;
    formalizations?: number;
  };
  gaps?: ShareGap[];
  releases?: ShareRelease[];
}

interface ShareRow {
  name: string;
  org: string;
  percent: string;
  alt: string;
}

type ReleaseKind = "new-result" | "formalization";

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

function percent(part: number, total: number): number {
  if (total <= 0) {
    throw new Error("share bar has an empty catalogue");
  }
  const quotient = Math.floor((part * 100) / total);
  const remainder = part * 100 - quotient * total;
  if (remainder * 2 < total) {
    return quotient;
  }
  if (remainder * 2 > total) {
    return quotient + 1;
  }
  return quotient % 2 === 0 ? quotient : quotient + 1;
}

function plural(count: number, singular: string, pluralForm?: string): string {
  const word = count === 1 ? singular : (pluralForm ?? `${singular}s`);
  return `${count} ${word}`;
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function catalogueBlocks(): ShareBlock[] {
  const blocks: ShareBlock[] = [];
  for (const value of Object.values(atlas)) {
    if (!isRecord(value) || !isRecord(value.source) || typeof value.source.id !== "string") {
      continue;
    }
    blocks.push(value as ShareBlock);
  }
  return blocks;
}

function blockFor(sourceId: string, name: string): ShareBlock | null {
  const matches = catalogueBlocks().filter((block) => block.source?.id === sourceId);
  if (matches.length > 1) {
    throw new Error(`${name} matches more than one catalogue`);
  }
  return matches[0] ?? null;
}

function familiesFor(sourceId: string): Family[] {
  return atlas.families.filter((family) => family.source === sourceId);
}

function leanBucket(status: LeanStatus): "main" | "challenge" | "paper" {
  switch (status) {
    case LEAN_MAIN:
      return "main";
    case LEAN_CHALLENGE:
      return "challenge";
    case LEAN_NONE:
      return "paper";
    default: {
      const exhaustive: never = status;
      throw new Error(`${String(exhaustive)} is a Lean status the share card cannot draw`);
    }
  }
}

function familyRow(name: string, org: string, families: Family[]): ShareRow {
  let main = 0;
  let challenge = 0;
  let paper = 0;
  for (const family of families) {
    const bucket = leanBucket(family.lean.status);
    switch (bucket) {
      case "main":
        main += 1;
        break;
      case "challenge":
        challenge += 1;
        break;
      case "paper":
        paper += 1;
        break;
      default: {
        const exhaustive: never = bucket;
        throw new Error(`${name} has a Lean status the share card cannot draw: ${String(exhaustive)}`);
      }
    }
  }
  const total = main + challenge + paper;
  if (total <= 0) {
    throw new Error(`${name} has no result families`);
  }
  const familyNoun = total === 1 ? "family" : "families";
  return {
    name,
    org,
    percent: `${percent(main + challenge, total)}%`,
    alt: `of ${total} ${familyNoun} (${main} main result, ${challenge} challenge only, ${paper} paper only)`,
  };
}

function gapSeries(gapId: string): string {
  const head = gapId.split("-")[0] ?? "";
  if (head.toLowerCase() === "oeis") {
    return head.toUpperCase();
  }
  throw new Error(`preview card cannot name the paper gap ${gapId}`);
}

function fileRow(name: string, org: string, block: ShareBlock): ShareRow {
  const files = integer(block.counts?.lean_files);
  if (files === null) {
    throw new Error(`${name} has no Lean-file count`);
  }
  const matched = (block.gaps ?? []).filter(
    (gap) =>
      typeof gap.id === "string" && gap.id.toLowerCase().startsWith("oeis") && integer(gap.absent) !== null,
  );
  if (matched.length !== 1) {
    throw new Error(`${name} needs one paper gap with an absent count`);
  }
  const absent = integer(matched[0]?.absent);
  const gapId = matched[0]?.id;
  if (absent === null || gapId === undefined) {
    throw new Error(`${name} needs one paper gap with an absent count`);
  }
  const total = files + absent;
  if (total <= 0) {
    throw new Error(`${name} has no files to share`);
  }
  if (gapSeries(gapId) === "") {
    throw new Error(`${name} needs one paper gap with an absent count`);
  }
  const fileNoun = files === 1 ? "file" : "files";
  return {
    name,
    org,
    percent: `${percent(files, total)}%`,
    alt: `(${files} ${fileNoun}, ${absent} paper only)`,
  };
}

function isReleaseKind(kind: string): kind is ReleaseKind {
  return kind === KIND_NEW || kind === KIND_FORMALIZATION;
}

function releaseBucket(kind: ReleaseKind): "new" | "formalization" {
  switch (kind) {
    case KIND_NEW:
      return "new";
    case KIND_FORMALIZATION:
      return "formalization";
    default: {
      const exhaustive: never = kind;
      throw new Error(`${String(exhaustive)} is a release kind the share card cannot draw`);
    }
  }
}

function releaseRow(name: string, org: string, block: ShareBlock): ShareRow {
  const releases = block.releases ?? [];
  if (releases.length === 0) {
    throw new Error(`${name} has no releases`);
  }
  const recorded = integer(block.counts?.releases);
  if (recorded !== null && recorded !== releases.length) {
    throw new Error(`${name} release count disagrees with its release list`);
  }
  let newResults = 0;
  let formalizations = 0;
  let withLean = 0;
  for (const release of releases) {
    const kind = release.kind ?? "";
    if (!isReleaseKind(kind)) {
      throw new Error(`${name} has a release kind the share card cannot draw`);
    }
    const bucket = releaseBucket(kind);
    switch (bucket) {
      case "new":
        newResults += 1;
        break;
      case "formalization":
        formalizations += 1;
        break;
      default: {
        const exhaustive: never = bucket;
        throw new Error(`${name} has a release kind the share card cannot draw: ${String(exhaustive)}`);
      }
    }
    const leanFiles = integer(release.counts?.lean_files);
    if (leanFiles === null) {
      throw new Error(`${name} has a release without a Lean-file count`);
    }
    if (leanFiles > 0) {
      withLean += 1;
    }
  }
  const recordedNew = integer(block.counts?.new_results);
  const recordedFormal = integer(block.counts?.formalizations);
  if (recordedNew !== null && recordedNew !== newResults) {
    throw new Error(`${name} new-result count disagrees with its releases`);
  }
  if (recordedFormal !== null && recordedFormal !== formalizations) {
    throw new Error(`${name} formalization count disagrees with its releases`);
  }
  const total = releases.length;
  return {
    name,
    org,
    percent: `${percent(withLean, total)}%`,
    alt: `(${withLean} of ${total}; ${plural(newResults, "new result")}, ${plural(formalizations, "formalization")})`,
  };
}

function rowFor(sourceId: string, name: string, org: string): ShareRow {
  const families = familiesFor(sourceId);
  const block = blockFor(sourceId, name);
  if (families.length > 0 && block !== null) {
    throw new Error(`${name} matches more than one share-card catalogue`);
  }
  if (families.length > 0) {
    return familyRow(name, org, families);
  }
  if (block === null) {
    throw new Error(`${name} has no catalogue the share card can draw`);
  }
  if (Array.isArray(block.releases)) {
    return releaseRow(name, org, block);
  }
  return fileRow(name, org, block);
}

function shareRows(): ShareRow[] {
  const rows: ShareRow[] = [];
  for (const source of atlas.sources.sources) {
    rows.push(rowFor(source.id, source.name, source.org));
  }
  if (rows.length === 0) {
    throw new Error("preview card has no sources");
  }
  return rows;
}

function formalizationNote(): string {
  for (const source of atlas.sources.sources) {
    const blob = `${source.preview.fragment}\n${source.preview.detail}`;
    if (blob.includes(FORMALIZATION_NOTE)) {
      return FORMALIZATION_NOTE;
    }
  }
  return "";
}

export function previewAltFromCatalogue(): string {
  const rows = shareRows();
  const body = rows.map((row) => `${row.name} ${row.percent} ${row.alt}`).join("; ");
  const note = formalizationNote();
  const line = affiliation(rows.map((row) => row.org));
  const alt = note
    ? `${SITE_NAME}. ${HEADLINE} ${SHARE_LABEL}: ${body}. ${note}. ${line}`
    : `${SITE_NAME}. ${HEADLINE} ${SHARE_LABEL}: ${body}. ${line}`;
  if (alt.length > SOCIAL_IMAGE_ALT_MAX) {
    throw new Error(`preview alt is ${alt.length} characters, over ${SOCIAL_IMAGE_ALT_MAX}`);
  }
  return alt;
}

export function absoluteUrl(site: URL, path: string): string {
  return new URL(path, site).href;
}
