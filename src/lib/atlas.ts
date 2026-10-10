import catalog from "../../data/families.json";
import type { LeanStatus } from "./lean";

export interface Manuscript {
  slug: string;
  title: string;
  date: string;
  pdf: string;
  main_result_formalized: boolean;
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
  source: string;
  title: string;
  areas: string[];
  upstream_summary: string;
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

export interface SourceInfo {
  id: string;
  name: string;
  org: string;
  repo: string;
  commit: string;
  paper: string | null;
  license: string;
  sync: string;
}

export interface NaturalLanguageProof {
  path: string;
  url: string;
}

export interface AlphaProofRecord {
  id: string;
  anchor: string;
  source: string;
  category: string;
  subcategory: string | null;
  filename: string;
  path: string;
  url: string;
  problem_id: string;
  erdos_number: number | null;
  part: string | null;
  variant: string | null;
  statement: string;
  scope_notes: string[];
  natural_language_proofs: NaturalLanguageProof[];
  provenance: string;
}

export interface AlphaProofGap {
  id: string;
  status: string;
  label: string;
  paper_count?: number;
  paper_attempted?: number;
  repo_files?: number;
  absent?: number;
  repo_newlines?: number;
  repo_entries?: number;
}

export interface AlphaProofData {
  source: SourceInfo;
  paper: {
    id: string;
    title: string;
    url: string;
    v1_submitted: string;
    v2_submitted: string;
    abstract_claim: string;
    table1_caption: string;
    density_note: string;
    agent_a: string;
  };
  quotations: string[];
  commit_date: string;
  commit_subject: string;
  lean_toolchain: string;
  upstream_ci: string;
  check_wording: string;
  provenance: {
    level: string;
    agent_d: string;
    agent_a: string;
    per_row: string;
    lean_paper: string;
    lean_repo: string;
  };
  counts: {
    lean_files: number;
    erdos: number;
    oeis_files: number;
    stacks: number;
    ai_collaborator: number;
    natural_language_pdfs: number;
    attempted_newlines: number;
    attempted_entries: number;
  };
  subcounts: Record<string, number>;
  gaps: AlphaProofGap[];
  records: AlphaProofRecord[];
}

export interface CrossJoin {
  method: string;
  shared: { number: number; openai_families: string[]; alphaproof_records: string[] }[];
  empty_text: string;
  openai_numbers: { number: number; families: string[] }[];
  alphaproof_numbers: { number: number; records: string[] }[];
}

export interface AtlasData {
  schema_version: number;
  generated_at: string;
  sources: { schema_version: number; sources: SourceInfo[] };
  alphaproof: AlphaProofData;
  cross: CrossJoin;
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
