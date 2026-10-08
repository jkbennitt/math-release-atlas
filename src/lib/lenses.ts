import type { Family } from "./atlas";

export const LENS_TAGS = [
  "condensed-matter",
  "plasma-kinetic",
  "fluids-continuum",
  "electronic-structure",
  "quantum-information",
  "gravity-qft",
  "computation-hardness",
] as const;

export type LensTag = (typeof LENS_TAGS)[number];

export type CommunityStatus = "claimed" | "community-confirmed" | "disputed" | "broken";

export function isLensTag(tag: string): tag is LensTag {
  switch (tag) {
    case "condensed-matter":
    case "plasma-kinetic":
    case "fluids-continuum":
    case "electronic-structure":
    case "quantum-information":
    case "gravity-qft":
    case "computation-hardness":
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
    case "community-confirmed":
    case "disputed":
    case "broken":
      return true;
    default:
      return false;
  }
}

export function communityLabel(status: CommunityStatus): string {
  switch (status) {
    case "claimed":
      return "Claimed";
    case "community-confirmed":
      return "Community confirmed";
    case "disputed":
      return "Disputed";
    case "broken":
      return "Broken";
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

export function lensCounts(families: Family[]): { tag: LensTag; count: number }[] {
  const counts = new Map<LensTag, number>(LENS_TAGS.map((tag) => [tag, 0]));
  for (const family of families) {
    for (const lens of family.lenses) {
      if (!isLensTag(lens.tag)) {
        continue;
      }
      counts.set(lens.tag, (counts.get(lens.tag) ?? 0) + 1);
    }
  }
  return LENS_TAGS.map((tag) => ({ tag, count: counts.get(tag) ?? 0 }));
}
