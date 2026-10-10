import type { LensNote } from "./atlas";

export const LENS_TAGS = [
  "condensed-matter",
  "plasma-kinetic",
  "fluids-continuum",
  "electronic-structure",
  "quantum-information",
  "gravity-qft",
  "computation-hardness",
  "number-theory",
  "combinatorics",
  "algebraic-geometry",
  "analysis",
] as const;

export type LensTag = (typeof LENS_TAGS)[number];

export const COMMUNITY_STATUSES = [
  "claimed",
  "community-checking",
  "independently-checked",
  "disputed",
  "retracted",
] as const;

export type CommunityStatus = (typeof COMMUNITY_STATUSES)[number];

export function isLensTag(tag: string): tag is LensTag {
  switch (tag) {
    case "condensed-matter":
    case "plasma-kinetic":
    case "fluids-continuum":
    case "electronic-structure":
    case "quantum-information":
    case "gravity-qft":
    case "computation-hardness":
    case "number-theory":
    case "combinatorics":
    case "algebraic-geometry":
    case "analysis":
      return true;
    default:
      return false;
  }
}

export function lensLabel(tag: LensTag): string {
  switch (tag) {
    case "condensed-matter":
      return "Condensed matter";
    case "plasma-kinetic":
      return "Plasma and kinetic theory";
    case "fluids-continuum":
      return "Fluids and continuum mechanics";
    case "electronic-structure":
      return "Electronic structure";
    case "quantum-information":
      return "Quantum information";
    case "gravity-qft":
      return "Gravity and quantum field theory";
    case "computation-hardness":
      return "Computation and hardness";
    case "number-theory":
      return "Number theory";
    case "combinatorics":
      return "Combinatorics";
    case "algebraic-geometry":
      return "Algebraic geometry";
    case "analysis":
      return "Analysis";
    default: {
      const exhaustive: never = tag;
      return exhaustive;
    }
  }
}

export function lensLabelFor(tag: string): string {
  if (!isLensTag(tag)) {
    return tag;
  }
  return lensLabel(tag);
}

export function isCommunityStatus(status: string): status is CommunityStatus {
  switch (status) {
    case "claimed":
    case "community-checking":
    case "independently-checked":
    case "disputed":
    case "retracted":
      return true;
    default:
      return false;
  }
}

export function communityLabel(status: CommunityStatus): string {
  switch (status) {
    case "claimed":
      return "Claimed";
    case "community-checking":
      return "Community checking";
    case "independently-checked":
      return "Independently checked";
    case "disputed":
      return "Disputed";
    case "retracted":
      return "Retracted";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

export function communityBlurb(status: CommunityStatus): string {
  switch (status) {
    case "claimed":
      return "Recorded as a claim. Evidence is optional.";
    case "community-checking":
      return "An outside check is underway. Evidence is required.";
    case "independently-checked":
      return "An outside check has been recorded. Evidence is required.";
    case "disputed":
      return "An outside note disagrees with the family. Evidence is required.";
    case "retracted":
      return "The claim was withdrawn. Evidence is required.";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

export function communityLabelFor(status: string | null | undefined): string {
  const value = status ?? "claimed";
  if (!isCommunityStatus(value)) {
    return value;
  }
  return communityLabel(value);
}

export function lensCounts(records: { lenses: LensNote[] }[]): { tag: LensTag; count: number }[] {
  const counts = new Map<LensTag, number>(LENS_TAGS.map((tag) => [tag, 0]));
  for (const record of records) {
    for (const lens of record.lenses) {
      if (!isLensTag(lens.tag)) {
        continue;
      }
      counts.set(lens.tag, (counts.get(lens.tag) ?? 0) + 1);
    }
  }
  return LENS_TAGS.map((tag) => ({ tag, count: counts.get(tag) ?? 0 }));
}
