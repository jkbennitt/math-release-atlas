import { atlas } from "./atlas";

export const SITE_NAME = "Math Release Atlas";
export const PREVIEW_IMAGE = "og.png";
export const PREVIEW_WIDTH = 1200;
export const PREVIEW_HEIGHT = 630;

// The dist check requires this sentence to match preview_alt() in scripts/atlaslib.py.
export function previewImageAlt(
  families: number,
  manuscripts: number,
  leanFiles = 0,
  oeisFiles = 0,
  oeisPaper = 0,
  oeisStatus = "",
  anthropicFiles = 0,
  anthropicNew = 0,
  anthropicFormalizations = 0,
): string {
  const catalogue = `${SITE_NAME}: ${families} result families and ${manuscripts} manuscripts from the OpenAI Math catalogue`;
  const second = leanFiles > 0 ? `, plus ${leanFiles} Lean files from AlphaProof Nexus` : "";
  const oeis =
    leanFiles > 0 && oeisPaper > 0 && oeisStatus
      ? `, OEIS ${oeisFiles} of ${oeisPaper} in paper (${oeisStatus})`
      : "";
  const noun = anthropicFormalizations === 1 ? "formalization" : "formalizations";
  const third = anthropicFiles
    ? `, plus ${anthropicFiles} Lean files from Anthropic (${anthropicNew} new results, ${anthropicFormalizations} ${noun})`
    : "";
  const affiliation = anthropicFiles
    ? "Unofficial, not affiliated with OpenAI, Google DeepMind, or Anthropic."
    : "Unofficial, not affiliated with OpenAI or Google DeepMind.";
  return `${catalogue}${second}${oeis}${third}. ${affiliation}`;
}

export function previewAltFromCatalogue(): string {
  const oeis = atlas.alphaproof.gaps.find((gap) => gap.id === "oeis-count");
  return previewImageAlt(
    atlas.counts.families,
    atlas.counts.manuscripts,
    atlas.alphaproof.counts.lean_files,
    atlas.alphaproof.counts.oeis_files,
    oeis?.paper_count ?? 0,
    oeis?.status ?? "",
    atlas.anthropic.counts.lean_files,
    atlas.anthropic.counts.new_results,
    atlas.anthropic.counts.formalizations,
  );
}

export function absoluteUrl(site: URL, path: string): string {
  return new URL(path, site).href;
}
