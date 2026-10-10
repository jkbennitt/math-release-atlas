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

export interface PreviewTile {
  value: string;
  label: string;
}

export interface PreviewBinding {
  value: string;
  path: string[];
}

export interface SourcePreview {
  fragment: string;
  tiles: PreviewTile[];
  detail: string;
  bindings: PreviewBinding[];
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
  preview: SourcePreview;
  also?: AlsoRepo[];
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
  lenses: LensNote[];
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

export interface AlsoRepo {
  label: string;
  repo: string;
  commit: string;
}

export interface AnthropicLicense {
  path: string;
  url: string;
  sha256: string;
}

export interface AnthropicStatementFile {
  path: string;
  url: string;
  role: string;
}

export interface AnthropicGap {
  id: string;
  status: string;
  label: string;
}

export interface AnthropicPaper {
  id: string;
  title: string;
  url: string;
  v1_submitted: string;
  v2_submitted: string | null;
}

export interface AnthropicTag {
  name: string;
  tag_object: string;
  commit: string;
}

export type AnthropicKind = "new-result" | "formalization";

export interface AnthropicRelease {
  id: string;
  kind: AnthropicKind;
  kind_label: string;
  title: string;
  statement: string;
  repo: string;
  commit: string;
  commit_date: string;
  commit_subject: string;
  path: string;
  tree_url: string;
  license: string;
  license_files: AnthropicLicense[];
  lean_toolchain: string;
  paper: AnthropicPaper | null;
  announcement: string | null;
  announcement_date: string | null;
  tag: AnthropicTag | null;
  headline_theorems: string[];
  xi_prime_theorems: string[];
  statement_files: AnthropicStatementFile[];
  axioms?: string[];
  scope_notes: string[];
  gaps: AnthropicGap[];
  lenses: LensNote[];
}

export interface AnthropicSource extends SourceInfo {
  also: AlsoRepo[];
}

export interface AnthropicQuotation {
  text: string;
  source: string;
}

export interface AnthropicData {
  source: AnthropicSource;
  check_wording: string;
  quotations: AnthropicQuotation[];
  counts: {
    releases: number;
    new_results: number;
    formalizations: number;
    lean_files: number;
  };
  identifiers: {
    erdos: string[];
    oeis: string[];
    stacks: string[];
    method: string;
  };
  skipped_directories: string[];
  releases: AnthropicRelease[];
  count_lines: string[];
}

export function anthropicLeanRank(kind: AnthropicKind): number {
  switch (kind) {
    case "new-result":
      return 4;
    case "formalization":
      return 5;
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

export interface CrossJoin {
  method: string;
  shared: { number: number; openai_families: string[]; alphaproof_records: string[] }[];
  empty_text: string;
  openai_numbers: { number: number; families: string[] }[];
  alphaproof_numbers: { number: number; records: string[] }[];
  anthropic_identifiers: {
    erdos: string[];
    oeis: string[];
    stacks: string[];
    method: string;
  };
  shared_with_anthropic: { kind: string; id: string }[];
  anthropic_empty_text: string;
}

export interface AtlasData {
  schema_version: number;
  generated_at: string;
  sources: { schema_version: number; sources: SourceInfo[] };
  alphaproof: AlphaProofData;
  anthropic: AnthropicData;
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
