import { atlas } from "./atlas";
import { lensLabel, type LensTag, LENS_TAGS } from "./lenses";

export interface NamedCount {
  name: string;
  count: number;
}

export interface LensChoice {
  tag: LensTag;
  label: string;
  count: number;
}

interface Carrier {
  areas: string[];
  lenses: string[];
}

function norm(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function carriers(): Carrier[] {
  return [
    ...atlas.families.map((family) => ({
      areas: family.areas,
      lenses: family.lenses.map((lens) => lens.tag),
    })),
    ...atlas.alphaproof.records.map((record) => ({
      areas: [record.category],
      lenses: record.lenses.map((lens) => lens.tag),
    })),
    ...atlas.anthropic.releases.map((release) => ({
      areas: [release.id],
      lenses: release.lenses.map((lens) => lens.tag),
    })),
  ];
}

const rows = carriers();

function lensTagForName(name: string): string {
  const key = norm(name);
  for (const tag of LENS_TAGS) {
    if (norm(lensLabel(tag)) === key) {
      return tag;
    }
  }
  return "";
}

function areaNameForTag(tag: string): string {
  const key = norm(lensLabel(tag as LensTag));
  return atlas.areas.find((area) => norm(area.name) === key)?.name ?? "";
}

function matchesArea(row: Carrier, name: string): boolean {
  const tag = lensTagForName(name);
  return row.areas.includes(name) || (tag !== "" && row.lenses.includes(tag));
}

function matchesLens(row: Carrier, tag: string): boolean {
  const area = areaNameForTag(tag);
  return row.lenses.includes(tag) || (area !== "" && row.areas.includes(area));
}

export function subjectChoices(): NamedCount[] {
  return atlas.areas.map((area) => ({
    name: area.name,
    count: rows.filter((row) => matchesArea(row, area.name)).length,
  }));
}

export function lensChoices(): LensChoice[] {
  return LENS_TAGS.map((tag) => ({
    tag,
    label: lensLabel(tag),
    count: rows.filter((row) => matchesLens(row, tag)).length,
  })).filter((choice) => choice.count > 0);
}
