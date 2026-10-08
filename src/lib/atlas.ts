import catalog from "../../data/families.json";
import type { LeanStatus } from "./lean";

export interface Manuscript {
  slug: string;
  title: string;
  date: string;
  pdf: string;
  main_result_formalized: boolean;
  title_withheld?: boolean;
}

export interface ComparatorLink {
  file: string;
  url: string;
  declarations: string[];
}

export interface LensNote {
  tag: string;
  why: string;
  source: string;
}

export interface RelatedNote {
  to: string;
  kind: string;
  why: string;
  source: string;
}

export interface EvidenceNote {
  url: string;
  date: string;
  note: string;
}

export interface StatusEvent {
  status: string;
  date: string;
  note: string;
  url?: string;
}

export interface CitationOut {
  to: string;
  via: string;
  source: string;
  url: string;
}

export interface CitationIn {
  from: string;
  via: string;
  source: string;
  url: string;
}

export interface Family {
  id: string;
  title: string;
  areas: string[];
  upstream_summary: string;
  upstream_summary_withheld?: boolean;
  manuscripts: Manuscript[];
  lean: {
    status: LeanStatus;
    doc: string | null;
    comparators: ComparatorLink[];
    upstream_review_status: string;
    scope: string;
  };
  reasoning_trace: { path: string; subject: string; url: string } | null;
  upstream_sha: string;
  caution: string | null;
  lenses: LensNote[];
  related: RelatedNote[];
  community: { status: string; evidence: EvidenceNote[]; history: StatusEvent[] } | null;
  cites: CitationOut[];
  cited_by: CitationIn[];
}

export interface AtlasData {
  schema_version: number;
  generated_at: string;
  upstream: {
    repo: string;
    commit: string;
    readme_sentence: string;
    readme_families: number;
    readme_manuscripts: number;
    contents_families: number;
    contents_manuscripts: number;
    formalization_scope: string;
    review_status: string;
    counts_match_readme: boolean;
  };
  counts: {
    families: number;
    manuscripts: number;
    main_result_formalized: number;
    comparator_challenge_only: number;
    none: number;
    yaml_sources: number;
    lean_docs: number;
    comparator_files: number;
    main_result_rows: number;
    reasoning_traces: number;
    areas: number;
  };
  areas: { name: string; families: number }[];
  families: Family[];
}

export const atlas = catalog as AtlasData;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatIso(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

export function dateRange(dates: string[]): string {
  const sorted = [...dates].sort();
  const first = formatIso(sorted[0]);
  const last = formatIso(sorted[sorted.length - 1]);
  return first === last ? first : `${first} – ${last}`;
}

export function shortSha(commit: string): string {
  return commit.slice(0, 12);
}
