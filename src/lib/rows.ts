import {
  atlas,
  type AlphaProofRecord,
  type AnthropicRelease,
  type Family,
  type LensNote,
} from "./atlas";

export interface DirectLink {
  href: string;
  label: string;
}

export type CatalogueSource = "openai-math" | "alphaproof-nexus" | "anthropic";

export interface LensRow {
  source: CatalogueSource;
  sourceLabel: string;
  sourceClass: string;
  kindClass: string | null;
  kindLabel: string | null;
  atlasPath: string;
  idLabel: string;
  title: string;
  direct: DirectLink[];
  why: string;
  lensSource: string;
}

export function openaiDirectHref(family: Family): string {
  return `${atlas.upstream.repo}/blob/${family.upstream_sha}/overview.tex#L${family.overview_line}`;
}

export function openaiDirectLinks(family: Family): DirectLink[] {
  return family.manuscripts.map((item, index) => ({
    href: item.pdf,
    label: family.manuscripts.length === 1 ? "Manuscript" : `Manuscript ${index + 1}`,
  }));
}

export function openaiUpstreamLinks(family: Family): DirectLink[] {
  return [{ href: openaiDirectHref(family), label: "Overview entry" }, ...openaiDirectLinks(family)];
}

export function alphaproofDirectLinks(record: AlphaProofRecord): DirectLink[] {
  return [{ href: record.url, label: "Lean file" }];
}

export function anthropicStatementHref(release: AnthropicRelease): string {
  const lean = release.statement_files.find((item) => item.path.endsWith(".lean"));
  if (lean) {
    return lean.url;
  }
  const readme = release.statement_files.find((item) => /(^|\/)README\.md$/.test(item.path));
  if (readme) {
    return readme.url;
  }
  throw new Error(`anthropic release ${release.id} has no Lean file or README link`);
}

export function anthropicDirectLinks(release: AnthropicRelease): DirectLink[] {
  const links: DirectLink[] = [];
  if (release.paper) {
    links.push({ href: release.paper.url, label: "Paper" });
  }
  links.push({ href: anthropicStatementHref(release), label: "Lean file" });
  links.push({ href: release.tree_url, label: "Lean folder" });
  return links;
}

export function lensCarriers(): { lenses: LensNote[] }[] {
  return [
    ...atlas.families,
    ...atlas.alphaproof.records,
    ...atlas.anthropic.releases,
  ];
}

type KnownGapStatus =
  | "NOT IN COMPARATOR"
  | "NOT FORMALIZED"
  | "NOTED"
  | "PARTIAL"
  | "MATCH"
  | "MORE THAN PAPER"
  | "MISSING";

function isKnownGapStatus(status: string): status is KnownGapStatus {
  switch (status) {
    case "NOT IN COMPARATOR":
    case "NOT FORMALIZED":
    case "NOTED":
    case "PARTIAL":
    case "MATCH":
    case "MORE THAN PAPER":
    case "MISSING":
      return true;
    default:
      return false;
  }
}

export function gapPlainStatus(status: string): string {
  if (!isKnownGapStatus(status)) {
    throw new Error(`unknown gap status: ${status}`);
  }
  switch (status) {
    case "NOT IN COMPARATOR":
      return "Not in the comparator";
    case "NOT FORMALIZED":
      return "Not formalized";
    case "NOTED":
      return "Noted";
    case "PARTIAL":
      return "Part of the paper count";
    case "MATCH":
      return "Matches the paper";
    case "MORE THAN PAPER":
      return "More than the paper";
    case "MISSING":
      return "Not recorded";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

export function provenanceLine(value: string): string {
  if (value === "MISSING") {
    return "no per-file agent record";
  }
  return value;
}

export function sourceChip(source: CatalogueSource): string {
  switch (source) {
    case "openai-math":
      return "OpenAI";
    case "alphaproof-nexus":
      return "APN";
    case "anthropic":
      return "Anthropic";
    default: {
      const exhaustive: never = source;
      return exhaustive;
    }
  }
}

function sourceBadge(source: CatalogueSource): { label: string; className: string } {
  switch (source) {
    case "openai-math":
      return { label: "OpenAI Math", className: "source-openai" };
    case "alphaproof-nexus":
      return { label: "AlphaProof Nexus", className: "source-alphaproof" };
    case "anthropic":
      return { label: "Anthropic", className: "source-anthropic" };
    default: {
      const exhaustive: never = source;
      return exhaustive;
    }
  }
}

export function lensRows(tag: string): LensRow[] {
  const rows: LensRow[] = [];
  for (const family of atlas.families) {
    for (const lens of family.lenses) {
      if (lens.tag !== tag) {
        continue;
      }
      const badge = sourceBadge("openai-math");
      rows.push({
        source: "openai-math",
        sourceLabel: badge.label,
        sourceClass: badge.className,
        kindClass: null,
        kindLabel: null,
        atlasPath: `f/${family.id}/`,
        idLabel: family.id,
        title: family.title,
        direct: openaiUpstreamLinks(family),
        why: lens.why,
        lensSource: lens.source,
      });
    }
  }
  for (const record of atlas.alphaproof.records) {
    for (const lens of record.lenses) {
      if (lens.tag !== tag) {
        continue;
      }
      const badge = sourceBadge("alphaproof-nexus");
      rows.push({
        source: "alphaproof-nexus",
        sourceLabel: badge.label,
        sourceClass: badge.className,
        kindClass: null,
        kindLabel: null,
        atlasPath: `source/alphaproof-nexus/#${record.anchor}`,
        idLabel: record.anchor,
        title: record.statement,
        direct: alphaproofDirectLinks(record),
        why: lens.why,
        lensSource: lens.source,
      });
    }
  }
  for (const release of atlas.anthropic.releases) {
    for (const lens of release.lenses) {
      if (lens.tag !== tag) {
        continue;
      }
      const badge = sourceBadge("anthropic");
      rows.push({
        source: "anthropic",
        sourceLabel: badge.label,
        sourceClass: badge.className,
        kindClass: release.kind,
        kindLabel: release.kind_label,
        atlasPath: `source/anthropic/#${release.id}`,
        idLabel: release.id,
        title: release.title,
        direct: anthropicDirectLinks(release),
        why: lens.why,
        lensSource: lens.source,
      });
    }
  }
  return rows;
}

export function lensSourceCounts(tag: string): Record<CatalogueSource, number> {
  const counts: Record<CatalogueSource, number> = {
    "openai-math": 0,
    "alphaproof-nexus": 0,
    anthropic: 0,
  };
  for (const row of lensRows(tag)) {
    counts[row.source] += 1;
  }
  return counts;
}
