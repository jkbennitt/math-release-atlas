#!/usr/bin/env python3
"""Build the AlphaProof Nexus snapshot from a pinned results checkout.

Records come from Lean files in the checkout. Natural-language PDFs are linked
only when the filename correspondence is exact. Paper counts that the checkout
does not contain stay as gaps. Nothing in this module invents a missing file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import anthropic_join, anthropic_preview
from atlaslib import (
    ROOT,
    UPSTREAM_WEB,
    AtlasError,
    git,
    list_tree,
    materialize_upstream,
    oeis_preview_phrase,
    read_json,
    snapshot_for_compare,
    write_json,
)

ALPHAPROOF_JSON = ROOT / "data" / "alphaproof.json"
SOURCES_JSON = ROOT / "data" / "sources.json"
ALPHAPROOF_URL = "https://github.com/google-deepmind/alphaproof-nexus-results.git"
ALPHAPROOF_WEB = "https://github.com/google-deepmind/alphaproof-nexus-results"
ALPHAPROOF_SOURCE_ID = "alphaproof-nexus"
OPENAI_SOURCE_ID = "openai-math"

PINNED_ALPHAPROOF_COMMIT = "0647711a71183c1ea492ad60860776617ce1ea88"
# SHA-256 of the pinned snapshot, ignoring generated_at and snapshot_digest.
# Filled after the first build from that commit and checked on every later build.
PINNED_ALPHAPROOF_DIGEST = "3154316e6483999d4859116c2c6e2c347f63acf59756cf6c13aedcc73585efa5"

PINNED_CATEGORY_COUNTS = {
    "ErdosProblems": 9,
    "OEIS": 38,
    "StacksProject": 11,
    "AICollaborator": 13,
}
PINNED_SUBCOUNTS = {
    "AdditiveCombinatorics": 1,
    "AlgebraicGeometry": 7,
    "Graphs": 2,
    "Optimization": 1,
    "QuantumOptics": 2,
}
PINNED_ATTEMPTED_NEWLINES = 352
PINNED_ATTEMPTED_ENTRIES = 353
PAPER_ERDOS_ATTEMPTED = 353
PAPER_OEIS_PROVED = 44
PAPER_OEIS_ATTEMPTED = 492
OEIS_GAP_LABEL = "not in repo / unexplained"
PROVENANCE_GAP_LABEL = "per-row provenance"

# The cross-source expectation is for these two commits only.
PINNED_OPENAI_COMMIT = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"
PINNED_OPENAI_ERDOS = {970: ["021"]}
PINNED_APN_ERDOS = {12, 26, 125, 138, 152, 741, 846}

ALPHAPROOF_SPARSE_PATHS = [
    "/APNOutputs/**",
    "/NaturalLanguageProofs/**",
    "/erdos_problems_attempted.txt",
    "/.github/workflows/lean_action_ci.yml",
    "/README.md",
    "/LICENSE",
    "/lean-toolchain",
]

# Verbatim upstream sentences from arXiv 2605.22763v2. The atlas quotes them
# and does not adopt them as its own wording.
ABSTRACT_CLAIM = (
    "Our most capable agent autonomously resolved 9 of 353 open Erdős problems "
    "at the per-problem cost of a few hundred dollars, proved 44/492 OEIS conjectures, "
    "and is being deployed in combinatorics, optimization, graph theory, algebraic geometry, "
    "and quantum optics research."
)
TABLE1_CAPTION = (
    "Open problems from the ErdosProblems repository autonomously resolved by our "
    "full-featured agent. The asterisk indicates a variant of the main problem with "
    "this number. Problem #26 (annotated with †) is a more general variant of a question "
    "posed by Erdős, but was not posed by Erdős himself."
)
DENSITY_NOTE = (
    "For example, in Erdős problems #125 and #741(i), the interpretation of “density” "
    "in the original informal statements was amended to “lower density” and “upper density” "
    "respectively, after our full-featured agent found proofs using density as “natural density.” "
    "Following the correction of the ambiguity, the agent was still able to resolve the questions."
)
AGENT_A_QUOTE = (
    "To understand the impact of the agent design on these results, we did a post-hoc "
    "analysis of the performance of the full-featured and basic agents, as well as two "
    "agents with intermediate capabilities, on the 9 Erdős problems solved by the "
    "full-featured agent. Remarkably, the basic agent solved all 9 problems, though at "
    "a higher cost on the harder problems."
)
QUOTATIONS = (ABSTRACT_CLAIM, TABLE1_CAPTION, DENSITY_NOTE, AGENT_A_QUOTE)

CATEGORY_ORDER = ("ErdosProblems", "OEIS", "StacksProject", "AICollaborator")
ERDOS_LEAN_RE = re.compile(
    r"^erdos_(?P<num>\d+)(?:\.parts\.(?P<part>[a-z]+))?(?:\.variants\.(?P<variant>[a-z0-9_]+))?$"
)
ERDOS_NUMBER_RE = re.compile(
    r"erdosproblems\.com/(?:problem/)?(?P<url>\d+)|erdos[_-]?(?P<num>\d+)",
    re.IGNORECASE,
)
LICENSE_MARKERS = (
    "Apache License, Version 2.0",
    "Creative Commons Attribution 4.0",
    "Attribution-Share-Alike License 4.0",
    "https://www.erdosproblems.com/",
    "https://oeis.org",
)

OPENAI_SOURCE = {
    "id": OPENAI_SOURCE_ID,
    "name": "OpenAI Math",
    "org": "OpenAI",
    "repo": UPSTREAM_WEB,
    "paper": None,
    "license": "Apache-2.0",
    "sync": "sparse-fetch",
}
ALPHAPROOF_SOURCE = {
    "id": ALPHAPROOF_SOURCE_ID,
    "name": "AlphaProof Nexus",
    "org": "Google DeepMind",
    "repo": ALPHAPROOF_WEB,
    "paper": "https://arxiv.org/abs/2605.22763",
    "license": (
        "Apache-2.0 code; CC-BY 4.0 other materials; OEIS-derived material CC BY-SA 4.0"
    ),
    "sync": "tree-snapshot",
}


def count_gap_status(paper: int, observed: int) -> str:
    """MATCH when the counts agree, PARTIAL when short, MORE THAN PAPER when ahead."""
    if observed < paper:
        return "PARTIAL"
    if observed > paper:
        return "MORE THAN PAPER"
    return "MATCH"


def surplus_label(extra: int, singular: str, plural: str) -> str:
    noun = singular if extra == 1 else plural
    return f"repo has {extra} more {noun} than paper"


def oeis_count_gap(repo_files: int) -> dict[str, Any]:
    """Label follows the file count against the paper's proved OEIS count."""
    absent = PAPER_OEIS_PROVED - repo_files
    status = count_gap_status(PAPER_OEIS_PROVED, repo_files)
    if status == "PARTIAL":
        label = OEIS_GAP_LABEL
    elif status == "MATCH":
        label = f"{repo_files} files, matching the paper"
    elif status == "MORE THAN PAPER":
        label = surplus_label(repo_files - PAPER_OEIS_PROVED, "file", "files")
    else:
        raise AtlasError(f"unknown OEIS count status {status}")
    return {
        "id": "oeis-count",
        "status": status,
        "paper_count": PAPER_OEIS_PROVED,
        "paper_attempted": PAPER_OEIS_ATTEMPTED,
        "repo_files": repo_files,
        "absent": absent,
        "label": label,
    }


def attempted_count_gap(entries: int, newlines: int) -> dict[str, Any]:
    """Status follows the distinct attempted lines against the paper count.

    A file with no trailing newline has one fewer newline than entries. That
    newline count is recorded and is not itself a gap.
    """
    status = count_gap_status(PAPER_ERDOS_ATTEMPTED, entries)
    if status == "PARTIAL":
        label = f"{entries} listed, {PAPER_ERDOS_ATTEMPTED} in paper"
    elif status == "MATCH":
        label = f"{entries} listed, matching the paper"
    elif status == "MORE THAN PAPER":
        label = surplus_label(entries - PAPER_ERDOS_ATTEMPTED, "entry", "entries")
    else:
        raise AtlasError(f"unknown attempted-count status {status}")
    return {
        "id": "erdos-attempted",
        "status": status,
        "paper_attempted": PAPER_ERDOS_ATTEMPTED,
        "repo_newlines": newlines,
        "repo_entries": entries,
        "label": label,
    }


def blob_url(commit: str, path: str) -> str:
    return f"{ALPHAPROOF_WEB}/blob/{commit}/{path}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"generated_at", "snapshot_digest"}}


def snapshot_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot_body(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def openai_preview(source: dict[str, Any], counts: dict[str, Any]) -> dict[str, Any]:
    """Card facts for the manuscript catalogue. Counts come from the merged catalogue."""
    families = int(counts["families"])
    manuscripts = int(counts["manuscripts"])
    name = source["name"]
    return {
        "fragment": (
            f"{families} result families and {manuscripts} manuscripts from the {name} catalogue"
        ),
        "tiles": [
            {"value": str(families), "label": "result families"},
            {"value": str(manuscripts), "label": "manuscripts"},
        ],
        "detail": "",
        "bindings": [
            {"value": str(families), "path": ["counts", "families"]},
            {"value": str(manuscripts), "path": ["counts", "manuscripts"]},
        ],
    }


def alphaproof_preview(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Card facts for AlphaProof Nexus. Status words are the gap statuses."""
    source = snapshot["source"]
    counts = snapshot["counts"]
    gaps = {gap["id"]: gap for gap in snapshot["gaps"]}
    oeis = gaps["oeis-count"]
    attempted = gaps["erdos-attempted"]
    provenance = gaps["per-row-provenance"]
    name = source["name"]
    lean = int(counts["lean_files"])
    oeis_files = int(counts["oeis_files"])
    paper = int(oeis["paper_count"])
    erdos = int(counts["erdos"])
    stacks = int(counts["stacks"])
    collaborator = int(counts["ai_collaborator"])
    phrase = oeis_preview_phrase(oeis_files, paper, str(oeis["status"]))
    fragment = (
        f"{lean} Lean files from {name}, {phrase}, "
        f"attempted list {attempted['status']}, per-row provenance {provenance['status']}"
    )
    return {
        "fragment": fragment,
        "tiles": [
            {"value": str(lean), "label": "Lean files"},
            {"value": str(oeis["status"]), "label": f"OEIS {oeis_files} of {paper}"},
            {"value": str(attempted["status"]), "label": "attempted list"},
            {"value": str(provenance["status"]), "label": "provenance"},
        ],
        "detail": f"Erdos {erdos}, Stacks {stacks}, AI collaborator {collaborator}",
        "bindings": [
            {"value": str(lean), "path": ["alphaproof", "counts", "lean_files"]},
            {"value": str(oeis["status"]), "path": ["alphaproof", "gaps", "oeis-count", "status"]},
            {"value": str(attempted["status"]), "path": ["alphaproof", "gaps", "erdos-attempted", "status"]},
            {"value": str(provenance["status"]), "path": ["alphaproof", "gaps", "per-row-provenance", "status"]},
            {"value": str(oeis_files), "path": ["alphaproof", "counts", "oeis_files"]},
            {"value": str(paper), "path": ["alphaproof", "gaps", "oeis-count", "paper_count"]},
            {"value": str(erdos), "path": ["alphaproof", "counts", "erdos"]},
            {"value": str(stacks), "path": ["alphaproof", "counts", "stacks"]},
            {"value": str(collaborator), "path": ["alphaproof", "counts", "ai_collaborator"]},
        ],
    }


def derived_source_previews(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Recompute previews from catalogue counts. A source that brings its own preview is left alone."""
    sources = catalog["sources"]["sources"]
    by_id = {source["id"]: source for source in sources}
    derived: dict[str, dict[str, Any]] = {}
    if OPENAI_SOURCE_ID in by_id:
        derived[OPENAI_SOURCE_ID] = openai_preview(by_id[OPENAI_SOURCE_ID], catalog["counts"])
    if ALPHAPROOF_SOURCE_ID in by_id and isinstance(catalog.get("alphaproof"), dict):
        derived[ALPHAPROOF_SOURCE_ID] = alphaproof_preview(catalog["alphaproof"])
    anthropic = catalog.get("anthropic")
    if isinstance(anthropic, dict):
        source_id = str(anthropic.get("source", {}).get("id", ""))
        if source_id in by_id:
            derived[source_id] = anthropic_preview(anthropic)
    return derived


def attach_previews(
    registry: dict[str, Any],
    upstream: dict[str, Any],
    alphaproof: dict[str, Any],
    anthropic: dict[str, Any] | None,
) -> None:
    """Write one preview onto every registered source. Known sources are derived; others must carry one."""
    catalog = {
        "counts": upstream["counts"],
        "sources": registry,
        "alphaproof": alphaproof,
    }
    if anthropic is not None:
        catalog["anthropic"] = anthropic
    derived = derived_source_previews(catalog)
    for source in registry["sources"]:
        expected = derived.get(source["id"])
        if expected is not None:
            source["preview"] = expected
            continue
        preview = source.get("preview")
        if not isinstance(preview, dict) or not preview.get("fragment") or not preview.get("tiles"):
            raise AtlasError(f"{source['id']} has no preview derived from its counts")


def catalogue_extras(
    upstream: dict[str, Any],
    alphaproof: dict[str, Any],
    anthropic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = [dict(anthropic["source"])] if anthropic is not None else None
    registry = source_registry(upstream["upstream"]["commit"], alphaproof["source"]["commit"], extra)
    attach_previews(registry, upstream, alphaproof, anthropic)
    records = alphaproof["records"]
    joined = cross_source(upstream["families"], records)
    if anthropic is not None:
        openai_erdos: set[int] = set()
        for family in upstream["families"]:
            openai_erdos.update(explicit_erdos_numbers(family))
        apn_erdos = {
            record["erdos_number"]
            for record in records
            if isinstance(record.get("erdos_number"), int)
        }
        other_text = "\n".join(
            f"{record.get('path', '')}\n{record.get('filename', '')}" for record in records
        )
        other_text += "\n" + json.dumps(upstream["families"], ensure_ascii=False)
        joined.update(anthropic_join(anthropic, openai_erdos, apn_erdos, other_text))
    payload = {
        "sources": registry,
        "alphaproof": alphaproof,
        "cross": joined,
    }
    if anthropic is not None:
        payload["anthropic"] = anthropic
    return payload


def source_registry(
    openai_commit: str,
    alphaproof_commit: str,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    openai = dict(OPENAI_SOURCE)
    openai["commit"] = openai_commit
    alphaproof = dict(ALPHAPROOF_SOURCE)
    alphaproof["commit"] = alphaproof_commit
    sources = [openai, alphaproof]
    if extra:
        sources.extend(extra)
    return {"schema_version": 1, "sources": sources}


def explicit_erdos_numbers(value: Any) -> set[int]:
    """Problem numbers written as erdos_<digits>, Erdos<digits>, or an erdosproblems.com path."""
    found: set[int] = set()
    if isinstance(value, str):
        for match in ERDOS_NUMBER_RE.finditer(value):
            raw = match.group("url") or match.group("num")
            found.add(int(raw))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(explicit_erdos_numbers(item))
    elif isinstance(value, list):
        for item in value:
            found.update(explicit_erdos_numbers(item))
    return found


def openai_erdos_index(families: list[dict[str, Any]]) -> dict[int, list[str]]:
    index: dict[int, list[str]] = {}
    for family in families:
        for number in sorted(explicit_erdos_numbers(family)):
            index.setdefault(number, []).append(family["id"])
    return index


def cross_source(families: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Join on an explicit Erdős problem number present in both catalogues.

    Titles are not compared. A number that only one side names stays off the join.
    """
    openai = openai_erdos_index(families)
    alphaproof: dict[int, list[str]] = {}
    for record in records:
        number = record.get("erdos_number")
        if isinstance(number, int):
            alphaproof.setdefault(number, []).append(record["id"])
    shared_numbers = sorted(set(openai) & set(alphaproof))
    shared = [
        {
            "number": number,
            "openai_families": openai[number],
            "alphaproof_records": alphaproof[number],
        }
        for number in shared_numbers
    ]
    return {
        "method": (
            "explicit erdos_<digits>, Erdos<digits>, or erdosproblems.com/<digits> on both sides"
        ),
        "shared": shared,
        "empty_text": "no shared problem ids at these commits" if not shared else "",
        "openai_numbers": [
            {"number": number, "families": openai[number]} for number in sorted(openai)
        ],
        "alphaproof_numbers": [
            {"number": number, "records": alphaproof[number]} for number in sorted(alphaproof)
        ],
    }


def erdos_scope_notes(number: int, part: str | None, variant: str | None) -> list[str]:
    notes: list[str] = []
    if number == 125 and variant == "positive_lower_density":
        notes.append(
            "Scope: variant positive_lower_density. For Erdős #125, density was amended "
            "to lower density after a misformalization was found."
        )
    if number == 741 and part == "i":
        notes.append(
            "Scope: part i. For Erdős #741(i), density was amended to upper density "
            "after a misformalization was found."
        )
    if number == 138 and variant == "difference":
        notes.append("Scope: variant difference. Paper Table 1 marks 138 as a variant (*).")
    if number == 26 and variant == "tenenbaum":
        notes.append(
            "Scope: variant tenenbaum. Paper Table 1 marks 26 as a variant (*) and as a "
            "variant not posed by Erdős himself (†)."
        )
    return notes


def erdos_statement(number: int, part: str | None, variant: str | None) -> str:
    label = f"Erdős #{number}"
    if part:
        label += f" part {part}"
    if variant:
        label += f" (variant {variant})"
    return f"Lean proof file deposited upstream for the formal statement of {label}."


def other_statement(category: str, filename: str) -> str:
    return (
        "Lean proof file deposited upstream for the formal statement in "
        f"{category} file {filename}."
    )


def anchor_for(
    category: str,
    path: str,
    number: int | None,
    part: str | None,
    variant: str | None,
) -> str:
    if category == "ErdosProblems" and number is not None:
        bits = ["erdos", str(number)]
        if part:
            bits.extend(("part", part))
        elif variant:
            bits.extend(("variant", variant.replace("_", "-")))
        return "-".join(bits)
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return slug


def _pdf_index(repo: Path) -> dict[str, Path]:
    root = repo / "NaturalLanguageProofs"
    if not root.is_dir():
        return {}
    return {path.relative_to(repo).as_posix(): path for path in sorted(root.rglob("*.pdf"))}


def _link_pdfs(repo: Path, records: list[dict[str, Any]], commit: str) -> list[str]:
    """Attach a PDF only when its filename corresponds to the Lean filename.

    Erdős PDFs use erdos{number}{part}. OEIS PDFs use oeis_{digits}. Other PDFs
    attach when the PDF stem is a substring of exactly the Lean filename and the
    stem is at least 6 characters.
    """
    pdfs = _pdf_index(repo)
    used: set[str] = set()
    by_erdos: dict[str, dict[str, Any]] = {}
    for record in records:
        if record["category"] == "ErdosProblems":
            stem = f"erdos{record['erdos_number']}{record['part'] or ''}"
            by_erdos.setdefault(stem, record)
    for rel, path in pdfs.items():
        name = path.stem
        rel_lower = rel.lower()
        matched: list[dict[str, Any]] = []
        if "/erdosproblems/" in rel_lower:
            target = by_erdos.get(name.lower())
            if target is not None:
                matched = [target]
        elif "/oeis/" in rel_lower:
            digits = re.fullmatch(r"oeis_(\d+)", name.lower())
            if digits:
                token = digits.group(1)
                matched = [
                    record
                    for record in records
                    if record["category"] == "OEIS"
                    and re.search(rf"(?<!\d){token}(?!\d)", record["filename"])
                ]
        else:
            if len(name) >= 6:
                needle = name.lower()
                matched = [
                    record
                    for record in records
                    if record["category"] == "AICollaborator" and needle in record["filename"].lower()
                ]
        if not matched:
            continue
        used.add(rel)
        link = {"path": rel, "url": blob_url(commit, rel), "sha256": file_sha256(path)}
        for record in matched:
            current = record["natural_language_proofs"]
            if all(item["path"] != rel for item in current):
                current.append(link)
    return sorted(set(pdfs) - used)


def _lean_paths(repo: Path) -> list[str]:
    root = repo / "APNOutputs"
    if not root.is_dir():
        raise AtlasError("APNOutputs is missing from the AlphaProof checkout")
    paths = sorted(path.relative_to(repo).as_posix() for path in root.rglob("*.lean") if path.is_file())
    if not paths:
        raise AtlasError("APNOutputs has no Lean files")
    return paths


def _require_tree_match(repo: Path, commit: str, lean_paths: list[str]) -> None:
    if not (repo / ".git").exists():
        return
    listed = [f"APNOutputs/{name}" for name in list_tree(repo, commit, "APNOutputs") if name.endswith(".lean")]
    if sorted(listed) != lean_paths:
        raise AtlasError("AlphaProof checkout Lean files do not match the commit tree")


def build_alphaproof(repo: Path, commit: str | None = None) -> dict[str, Any]:
    if commit is None:
        commit = git(repo, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AtlasError(f"unexpected AlphaProof commit sha: {commit}")
    readme_path = repo / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        missing = [phrase for phrase in LICENSE_MARKERS if phrase not in readme]
        if missing:
            raise AtlasError(f"AlphaProof README is missing license text: {missing[0]}")
    toolchain_path = repo / "lean-toolchain"
    ci_path = repo / ".github" / "workflows" / "lean_action_ci.yml"
    attempted_path = repo / "erdos_problems_attempted.txt"
    if not toolchain_path.is_file() or not ci_path.is_file() or not attempted_path.is_file():
        raise AtlasError("AlphaProof checkout is missing the toolchain, CI workflow, or attempted list")
    toolchain = toolchain_path.read_text(encoding="utf-8").strip()
    ci_text = ci_path.read_text(encoding="utf-8")
    if "leanprover/lean-action" not in ci_text:
        raise AtlasError("AlphaProof CI workflow does not name lean-action")
    attempted_text = attempted_path.read_text(encoding="utf-8")
    attempted_entries = [line for line in attempted_text.splitlines() if line.strip()]
    if len(attempted_text.splitlines()) != len(attempted_entries):
        raise AtlasError("erdos_problems_attempted.txt has a blank line")
    attempted_newlines = attempted_text.count("\n")
    committed = git(repo, "log", "-1", "--format=%cI%n%s").splitlines() if (repo / ".git").exists() else ["", ""]
    commit_date = committed[0][:10] if committed and committed[0] else ""
    commit_subject = committed[1] if len(committed) > 1 else ""

    lean_paths = _lean_paths(repo)
    _require_tree_match(repo, commit, lean_paths)
    records: list[dict[str, Any]] = []
    for rel in lean_paths:
        path = repo / rel
        parts = Path(rel).parts
        if len(parts) < 3 or parts[0] != "APNOutputs":
            raise AtlasError(f"unexpected Lean path {rel}")
        category = parts[1]
        if category not in CATEGORY_ORDER:
            raise AtlasError(f"unknown AlphaProof category {category}")
        subcategory = parts[2] if category == "AICollaborator" and len(parts) > 3 else None
        filename = parts[-1]
        stem = filename[: -len(".lean")]
        erdos_number = None
        part = None
        variant = None
        if category == "ErdosProblems":
            match = ERDOS_LEAN_RE.fullmatch(stem)
            if match is None:
                raise AtlasError(f"Erdős filename was not parsed: {filename}")
            erdos_number = int(match.group("num"))
            part = match.group("part")
            variant = match.group("variant")
            statement = erdos_statement(erdos_number, part, variant)
            scope_notes = erdos_scope_notes(erdos_number, part, variant)
            problem_id = f"erdos_{erdos_number}"
            if part:
                problem_id += f".parts.{part}"
            if variant:
                problem_id += f".variants.{variant}"
        else:
            statement = other_statement(category, filename)
            scope_notes = []
            problem_id = stem
        records.append(
            {
                "id": rel,
                "anchor": anchor_for(category, rel, erdos_number, part, variant),
                "source": ALPHAPROOF_SOURCE_ID,
                "category": category,
                "subcategory": subcategory,
                "filename": filename,
                "path": rel,
                "url": blob_url(commit, rel),
                "sha256": file_sha256(path),
                "problem_id": problem_id,
                "erdos_number": erdos_number,
                "part": part,
                "variant": variant,
                "statement": statement,
                "scope_notes": scope_notes,
                "natural_language_proofs": [],
                "provenance": "MISSING",
            }
        )
    unlinked = _link_pdfs(repo, records, commit)
    counts = {
        "lean_files": len(records),
        "erdos": sum(1 for record in records if record["category"] == "ErdosProblems"),
        "oeis_files": sum(1 for record in records if record["category"] == "OEIS"),
        "stacks": sum(1 for record in records if record["category"] == "StacksProject"),
        "ai_collaborator": sum(1 for record in records if record["category"] == "AICollaborator"),
        "natural_language_pdfs": len(_pdf_index(repo)),
        "linked_natural_language_pdfs": len(_pdf_index(repo)) - len(unlinked),
        "unlinked_natural_language_pdfs": len(unlinked),
        "attempted_newlines": attempted_newlines,
        "attempted_entries": len(attempted_entries),
    }
    subcounts: dict[str, int] = {}
    for record in records:
        if record["subcategory"]:
            subcounts[record["subcategory"]] = subcounts.get(record["subcategory"], 0) + 1
    gaps = [
        oeis_count_gap(counts["oeis_files"]),
        attempted_count_gap(counts["attempted_entries"], counts["attempted_newlines"]),
        {
            "id": "per-row-provenance",
            "status": "MISSING",
            "label": PROVENANCE_GAP_LABEL,
        },
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            **ALPHAPROOF_SOURCE,
            "commit": commit,
        },
        "paper": {
            "id": "2605.22763",
            "title": "Advancing Mathematics Research with AI-Driven Formal Proof Search",
            "url": "https://arxiv.org/abs/2605.22763",
            "v1_submitted": "2026-05-21",
            "v2_submitted": "2026-06-08",
            "abstract_claim": ABSTRACT_CLAIM,
            "table1_caption": TABLE1_CAPTION,
            "density_note": DENSITY_NOTE,
            "agent_a": AGENT_A_QUOTE,
        },
        "quotations": list(QUOTATIONS),
        "commit_date": commit_date,
        "commit_subject": commit_subject,
        "lean_toolchain": toolchain,
        "upstream_ci": ".github/workflows/lean_action_ci.yml",
        "upstream_ci_sha256": file_sha256(ci_path),
        "attempted_list": "erdos_problems_attempted.txt",
        "attempted_sha256": file_sha256(attempted_path),
        "check_wording": "Lean file deposited upstream; upstream CI builds it. This atlas did not run Lean.",
        "provenance": {
            "level": "source",
            "agent_d": (
                "Agent D (full-featured) uses Gemini 3.1 Pro prover subagents, "
                "Gemini 3.0 Flash Elo rating agents, evolutionary P-UCB search, "
                "the AlphaProof tool, and SafeVerify."
            ),
            "agent_a": (
                "The basic agent A also reproduced all 9 Erdős results in post-hoc analysis. "
                "The repository has no per-file agent record."
            ),
            "per_row": "MISSING",
            "lean_paper": "Lean v4.27 in the paper sandbox, with checks by SafeVerify.",
            "lean_repo": toolchain,
        },
        "counts": counts,
        "subcounts": subcounts,
        "gaps": gaps,
        "unlinked_natural_language_proofs": unlinked,
        "records": records,
    }
    payload["snapshot_digest"] = snapshot_digest(payload)
    assert_alphaproof(payload)
    return payload


def assert_alphaproof(payload: dict[str, Any]) -> None:
    records = payload["records"]
    counts = payload["counts"]
    derived = {
        "lean_files": len(records),
        "erdos": sum(1 for record in records if record["category"] == "ErdosProblems"),
        "oeis_files": sum(1 for record in records if record["category"] == "OEIS"),
        "stacks": sum(1 for record in records if record["category"] == "StacksProject"),
        "ai_collaborator": sum(1 for record in records if record["category"] == "AICollaborator"),
        "attempted_newlines": payload["counts"]["attempted_newlines"],
        "attempted_entries": payload["counts"]["attempted_entries"],
    }
    for key, value in derived.items():
        if counts.get(key) != value:
            raise AtlasError(f"AlphaProof count {key} is {counts.get(key)} in the file and {value} in the rows")
    if counts["lean_files"] != counts["erdos"] + counts["oeis_files"] + counts["stacks"] + counts["ai_collaborator"]:
        raise AtlasError("AlphaProof category counts do not add up to the Lean file count")
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise AtlasError("AlphaProof records repeat a path")
    anchors = [record["anchor"] for record in records]
    if len(anchors) != len(set(anchors)):
        raise AtlasError("AlphaProof records repeat an anchor")
    for record in records:
        if record["source"] != ALPHAPROOF_SOURCE_ID:
            raise AtlasError(f"{record['id']} is not source {ALPHAPROOF_SOURCE_ID}")
        if record["provenance"] != "MISSING":
            raise AtlasError(f"{record['id']} has per-row provenance")
        if "solved" in record["statement"].lower() or "proves" in record["statement"].lower():
            raise AtlasError(f"{record['id']} statement uses a bare claim")
        if record["category"] == "ErdosProblems" and not isinstance(record["erdos_number"], int):
            raise AtlasError(f"{record['id']} has no Erdős number")
        if record["category"] != "ErdosProblems" and record["erdos_number"] is not None:
            raise AtlasError(f"{record['id']} invented an Erdős number")
    oeis_gap = next(gap for gap in payload["gaps"] if gap["id"] == "oeis-count")
    expected_oeis = oeis_count_gap(counts["oeis_files"])
    if oeis_gap["status"] != expected_oeis["status"] or oeis_gap["paper_count"] != PAPER_OEIS_PROVED:
        raise AtlasError("OEIS paper count drifted")
    if oeis_gap["absent"] != expected_oeis["absent"] or oeis_gap["label"] != expected_oeis["label"]:
        raise AtlasError("OEIS paper count drifted")
    if oeis_gap["repo_files"] != counts["oeis_files"] or "entries" in oeis_gap:
        raise AtlasError("OEIS gap invented entries")
    attempted = next(gap for gap in payload["gaps"] if gap["id"] == "erdos-attempted")
    expected_attempted = attempted_count_gap(counts["attempted_entries"], counts["attempted_newlines"])
    if attempted["status"] != expected_attempted["status"] or attempted["label"] != expected_attempted["label"]:
        raise AtlasError("attempted-count gap drifted")
    if attempted["paper_attempted"] != PAPER_ERDOS_ATTEMPTED:
        raise AtlasError("attempted-count gap drifted")
    if attempted["repo_newlines"] != counts["attempted_newlines"]:
        raise AtlasError("attempted-count gap does not match the newline count")
    if attempted["repo_entries"] != counts["attempted_entries"]:
        raise AtlasError("attempted-count gap does not match the entry count")
    provenance = next(gap for gap in payload["gaps"] if gap["id"] == "per-row-provenance")
    if provenance["status"] != "MISSING" or provenance["label"] != PROVENANCE_GAP_LABEL:
        raise AtlasError("per-row provenance is not MISSING")
    if payload["paper"]["abstract_claim"] not in payload["quotations"]:
        raise AtlasError("AlphaProof abstract quotation is not in the exemption list")
    commit = payload["source"]["commit"]
    if commit == PINNED_ALPHAPROOF_COMMIT:
        for category, expected in PINNED_CATEGORY_COUNTS.items():
            key = {
                "ErdosProblems": "erdos",
                "OEIS": "oeis_files",
                "StacksProject": "stacks",
                "AICollaborator": "ai_collaborator",
            }[category]
            if counts[key] != expected:
                raise AtlasError(f"pinned AlphaProof {key} is {counts[key]}, expected {expected}")
        if counts["attempted_newlines"] != PINNED_ATTEMPTED_NEWLINES:
            raise AtlasError("pinned attempted-list newline count drifted")
        if counts["attempted_entries"] != PINNED_ATTEMPTED_ENTRIES:
            raise AtlasError("pinned attempted-list entry count drifted")
        if counts["attempted_entries"] != PAPER_ERDOS_ATTEMPTED or attempted["status"] != "MATCH":
            raise AtlasError("pinned attempted list does not match the paper")
        if payload["subcounts"] != PINNED_SUBCOUNTS:
            raise AtlasError(f"pinned AI collaborator subcounts are {payload['subcounts']}")
        if oeis_gap["absent"] != PAPER_OEIS_PROVED - PINNED_CATEGORY_COUNTS["OEIS"]:
            raise AtlasError("pinned OEIS gap is not 6")
        if payload["lean_toolchain"] != "leanprover/lean4:v4.27.0":
            raise AtlasError("pinned lean-toolchain drifted")
        digest = snapshot_digest(payload)
        if digest != PINNED_ALPHAPROOF_DIGEST:
            raise AtlasError(f"pinned AlphaProof snapshot digest drifted: {digest}")
        numbers = {record["erdos_number"] for record in records if record["erdos_number"] is not None}
        if numbers != PINNED_APN_ERDOS:
            raise AtlasError(f"pinned Erdős numbers are {sorted(numbers)}")
        if payload["unlinked_natural_language_proofs"]:
            raise AtlasError(f"pinned checkout left PDFs unlinked: {payload['unlinked_natural_language_proofs']}")


def assert_cross_source(
    openai_commit: str,
    alphaproof_commit: str,
    families: list[dict[str, Any]],
    records: list[dict[str, Any]],
    joined: dict[str, Any],
) -> None:
    rebuilt = cross_source(families, records)
    if rebuilt["shared"] != joined.get("shared"):
        raise AtlasError("stored cross-source join does not match the records")
    if openai_commit != PINNED_OPENAI_COMMIT or alphaproof_commit != PINNED_ALPHAPROOF_COMMIT:
        return
    if joined["shared"]:
        raise AtlasError("pinned catalogues were joined on a problem id")
    if joined.get("empty_text") != "no shared problem ids at these commits":
        raise AtlasError("pinned cross-source view does not say there is no shared id")
    openai = {item["number"]: item["families"] for item in joined["openai_numbers"]}
    if openai != PINNED_OPENAI_ERDOS:
        raise AtlasError(f"pinned OpenAI Erdős numbers are {openai}")
    alphaproof = {item["number"] for item in joined["alphaproof_numbers"]}
    if alphaproof != PINNED_APN_ERDOS:
        raise AtlasError(f"pinned AlphaProof Erdős numbers are {sorted(alphaproof)}")


def verify_recorded_alphaproof() -> None:
    """Rebuild data/alphaproof.json from the commit it names and fail on any difference.

    The commit must be alphaproof-nexus-results HEAD or an ancestor of it.
    generated_at is ignored. A fetch or network failure is an AtlasError.
    """
    recorded = read_json(ALPHAPROOF_JSON)
    commit = str(recorded.get("source", {}).get("commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AtlasError("alphaproof.json has no commit sha")
    with tempfile.TemporaryDirectory(prefix="atlas-alphaproof-") as tmp:
        checkout = Path(tmp) / "alphaproof"
        materialize_upstream(ALPHAPROOF_URL, commit, checkout, ALPHAPROOF_SPARSE_PATHS)
        rebuilt = build_alphaproof(checkout)
    if snapshot_body(recorded) != snapshot_body(rebuilt):
        raise AtlasError(f"alphaproof.json differs from commit {commit}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, help="Existing clone already at the commit.")
    parser.add_argument("--sha", help="Commit to fetch when --checkout is omitted.")
    args = parser.parse_args()
    if args.checkout:
        payload = build_alphaproof(args.checkout, args.sha)
    else:
        sha = args.sha or PINNED_ALPHAPROOF_COMMIT
        with tempfile.TemporaryDirectory(prefix="atlas-alphaproof-") as tmp:
            checkout = Path(tmp) / "alphaproof"
            materialize_upstream(ALPHAPROOF_URL, sha, checkout, ALPHAPROOF_SPARSE_PATHS)
            payload = build_alphaproof(checkout)
    write_json(ALPHAPROOF_JSON, payload)
    print(f"wrote {ALPHAPROOF_JSON}")
    print(f"digest {payload['snapshot_digest']}")
    print(
        "counts "
        f"erdos={payload['counts']['erdos']} "
        f"oeis={payload['counts']['oeis_files']} "
        f"stacks={payload['counts']['stacks']} "
        f"ai={payload['counts']['ai_collaborator']}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
