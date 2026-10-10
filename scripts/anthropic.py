#!/usr/bin/env python3
"""Build the Anthropic snapshot from pinned upstream trees.

Counts come from ``git ls-tree`` at the commits named in the snapshot.
Fermat's Last Theorem is not checked out in full: only its statement files
are fetched, and the Lean-file totals come from the tree listing. Statement
files are linked, not copied. A directory that is not one of the three
releases is recorded as skipped and is not given a section.
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

from atlaslib import (
    ROOT,
    AtlasError,
    git,
    materialize_upstream,
    read_json,
    run_git,
    write_json,
)

ANTHROPIC_JSON = ROOT / "data" / "anthropic.json"
FORMAL_MATH_URL = "https://github.com/anthropics/formal-math.git"
FORMAL_MATH_WEB = "https://github.com/anthropics/formal-math"
FLT_URL = "https://github.com/anthropics/fermats-last-theorem.git"
FLT_WEB = "https://github.com/anthropics/fermats-last-theorem"
ANTHROPIC_SOURCE_ID = "anthropic"

PINNED_FORMAL_MATH_COMMIT = "e1a4e6508154ea59f030480661590a9fe3018011"
PINNED_FLT_COMMIT = "6e837e75355538c7f80bab5b956861e86c4eacc2"
PINNED_ZETA_TAG = "v1.0"
PINNED_ZETA_TAG_COMMIT = "3635e74826a4c1fcece7d1cd2b6fa75e43a00510"
# SHA-256 of the pinned snapshot, ignoring generated_at and snapshot_digest.
# Filled after the first build from those commits and checked on every later build.
PINNED_ANTHROPIC_DIGEST = "f4c3e0ed551670824ac611b3299220b734fb4690c9e15382b2c288e865a59b54"

RELEASE_IDS = ("zeta23", "3sum-apsp", "fermat-last-theorem")
FORMAL_MATH_PROJECTS = ("zeta23", "3sum-apsp")
IGNORED_TOP_LEVEL = {".github"}

FORMAL_MATH_SPARSE_PATHS = [
    "/LICENSE",
    "/README.md",
    "/zeta23/**",
    "/3sum-apsp/**",
]
FLT_SPARSE_PATHS = [
    "/LICENSE",
    "/README.md",
    "/NOTICE",
    "/lean-toolchain",
    "/formalization.yaml",
    "/FinalCheck.lean",
]

CHECK_WORDING = "Lean files deposited upstream. This atlas did not run Lean."
IDENTIFIER_METHOD = (
    "explicit erdos_<digits>, oeis_<digits>, an OEIS A-number, or a Stacks project URL "
    "in pinned paths and in the statement files fetched for each release"
)
ANTHROPIC_EMPTY_TEXT = (
    "no shared Erdős, OEIS, or Stacks ids with OpenAI Math or AlphaProof Nexus"
)
NOT_FORMALIZED_LABEL = "real-number inputs and some running-time claims are not formalized"
PAIR_CEILING_LABEL = "bandwidth-one ceiling is a separate topic and is not a comparator configuration"

# Verbatim sentences. The atlas quotes them and does not adopt them as its own wording.
ZETA_ARXIV_COMMENT = (
    "Proof discovered autonomously by Claude (Anthropic); verified and communicated "
    "by the listed authors."
)
THREESUM_DISCOVERY = (
    "Claude, an AI model developed by Anthropic, discovered the algorithm that refutes "
    "the 3SUM, APSP, and Exact Triangle hypotheses."
)
THREESUM_RESPONSIBILITY = "The authors take full responsibility for this paper."
ZETA_QUOTE_SOURCE = "zeta arXiv comment"
THREESUM_QUOTE_SOURCE = "3SUM paper"
QUOTATIONS = (
    {"text": ZETA_ARXIV_COMMENT, "source": ZETA_QUOTE_SOURCE},
    {"text": THREESUM_DISCOVERY, "source": THREESUM_QUOTE_SOURCE},
    {"text": THREESUM_RESPONSIBILITY, "source": THREESUM_QUOTE_SOURCE},
)

ERDOS_RE = re.compile(
    r"erdos[_-]?(?P<num>\d+)|erdosproblems\.com/(?:problem/)?(?P<url>\d+)",
    re.IGNORECASE,
)
OEIS_RE = re.compile(r"\boeis[_-]?(?P<num>\d+)\b|\bA(?P<a>\d{6})\b", re.IGNORECASE)
STACKS_RE = re.compile(
    r"stacksproject|stacks-project|stacks\.math\.columbia",
    re.IGNORECASE,
)
README_MODULES_RE = re.compile(r"All ([\d,]+) modules of this repository built")
CHALLENGE_NOT_PACKAGE_RE = re.compile(r"Challenge\.lean`?[^.]*is not part of the package")
# FinalCheck.lean sits outside Theorems, P2M, and Definitions and is still a package module.
PACKAGE_ROOT_FILES = ("FinalCheck.lean",)
APACHE_MARKERS = ("Apache License", "Version 2.0")
ZETA_SUBJECT = (
    "a lower bound on the proportion of zeta zeros that are simple and on the critical line "
    "(more than two thirds)"
)
NOT_RH = "It is not the Riemann Hypothesis."


def anthropic_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Card facts for this source. Every number is taken from the snapshot counts."""
    counts = payload["counts"]
    name = payload["source"]["name"]
    lean = int(counts["lean_files"])
    releases = int(counts["releases"])
    new_results = int(counts["new_results"])
    formalizations = int(counts["formalizations"])
    release_noun = "release" if releases == 1 else "releases"
    result_noun = "new result" if new_results == 1 else "new results"
    formalization_noun = "formalization" if formalizations == 1 else "formalizations"
    fragment = (
        f"{lean} Lean files from {name} "
        f"({releases} {release_noun}, {new_results} {result_noun}, "
        f"{formalizations} {formalization_noun})"
    )
    return {
        "fragment": fragment,
        "tiles": [
            {"value": str(lean), "label": "Lean files"},
            {"value": str(releases), "label": release_noun},
            {"value": str(new_results), "label": result_noun},
            {"value": str(formalizations), "label": formalization_noun},
        ],
        "detail": "",
        "bindings": [
            {"value": str(lean), "path": ["anthropic", "counts", "lean_files"]},
            {"value": str(releases), "path": ["anthropic", "counts", "releases"]},
            {"value": str(new_results), "path": ["anthropic", "counts", "new_results"]},
            {"value": str(formalizations), "path": ["anthropic", "counts", "formalizations"]},
        ],
    }


def snapshot_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"generated_at", "snapshot_digest"}}


def snapshot_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot_body(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def file_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def blob_url(web: str, commit: str, path: str) -> str:
    return f"{web}/blob/{commit}/{path}"


def tree_url(web: str, commit: str, path: str) -> str:
    return f"{web}/tree/{commit}/{path}"


def list_paths(repo: Path) -> list[str]:
    output = git(repo, "ls-tree", "-r", "--name-only", "HEAD")
    return [line for line in output.splitlines() if line]


def find_identifiers(*texts: str) -> dict[str, list[str]]:
    """Explicit catalogue ids. A camel-case fragment such as pseudoEisenstein is not an id."""
    erdos: set[int] = set()
    oeis: set[str] = set()
    stacks: set[str] = set()
    for text in texts:
        for match in ERDOS_RE.finditer(text):
            raw = match.group("url") or match.group("num")
            erdos.add(int(raw))
        for match in OEIS_RE.finditer(text):
            oeis.add(match.group("num") or match.group("a"))
        for match in STACKS_RE.finditer(text):
            stacks.add(match.group(0))
    return {
        "erdos": [str(number) for number in sorted(erdos)],
        "oeis": sorted(oeis),
        "stacks": sorted(set(stacks)),
    }


def classify_flt(paths: list[str]) -> dict[str, Any]:
    lean = [path for path in paths if path.endswith(".lean")]
    other = sorted(
        path
        for path in lean
        if not path.startswith(("Theorems/", "P2M/", "Definitions/"))
    )
    return {
        "lean_files": len(lean),
        "theorem_files": sum(1 for path in lean if path.startswith("Theorems/")),
        "proof_files": sum(1 for path in lean if path.startswith("P2M/")),
        "definition_files": sum(1 for path in lean if path.startswith("Definitions/")),
        "other_lean_files": other,
    }


def count_lines(payload: dict[str, Any]) -> list[str]:
    """Visible count rows. Each figure is taken from the snapshot counts."""
    by_id = {release["id"]: release for release in payload["releases"]}
    zeta = by_id["zeta23"]["counts"]
    three = by_id["3sum-apsp"]["counts"]
    flt = by_id["fermat-last-theorem"]["counts"]
    totals = payload["counts"]
    return [
        f"zeta23: {zeta['lean_files']} Lean files.",
        f"zeta23: {zeta['headline_theorems']} headline theorems in the comparator configuration.",
        f"zeta23: {zeta['xi_prime_statements']} statements in the xi-prime comparator configuration.",
        f"3sum-apsp: {three['lean_files']} Lean files.",
        f"3sum-apsp: {three['headline_theorems']} headline theorems in EndStatement.",
        f"3sum-apsp: {three['paper_statement_theorems']} theorem names in the paper-statements comparator.",
        f"fermat-last-theorem: {flt['lean_files']} Lean files.",
        f"fermat-last-theorem: {flt['theorem_files']} theorem files.",
        f"fermat-last-theorem: {flt['proof_files']} proof files.",
        f"fermat-last-theorem: {flt['definition_files']} definition files.",
        f"All releases: {totals['lean_files']} Lean files.",
        f"All releases: {totals['new_results']} new results.",
        f"All releases: {totals['formalizations']} formalization.",
    ]


def _oxford(paths: list[str]) -> str:
    if not paths:
        return "none"
    if len(paths) == 1:
        return paths[0]
    if len(paths) == 2:
        return f"{paths[0]} and {paths[1]}"
    return ", ".join(paths[:-1]) + ", and " + paths[-1]


def module_count_label(readme_modules: int, classified: dict[str, Any], readme_text: str) -> str:
    """Explain the README module count from the tree.

    The README count is the files under Theorems, P2M, and Definitions plus
    FinalCheck.lean. Remaining .lean files, including lakefile.lean and the
    comparator files, are not package modules. The Challenge.lean sentence is
    copied only when the README states it.
    """
    package_dirs = (
        classified["theorem_files"] + classified["proof_files"] + classified["definition_files"]
    )
    other = list(classified["other_lean_files"])
    package_other = [path for path in other if path in PACKAGE_ROOT_FILES]
    non_package = [path for path in other if path not in PACKAGE_ROOT_FILES]
    package_total = package_dirs + len(package_other)
    included = _oxford(package_other)
    extra_names = _oxford(non_package)
    challenge_note = ""
    if any(path.endswith("Challenge.lean") for path in non_package) and CHALLENGE_NOT_PACKAGE_RE.search(
        readme_text
    ):
        challenge_note = " The README says Challenge.lean is not part of the package."
    if package_total == readme_modules:
        return (
            f"README says {readme_modules} modules, which is the {package_dirs} files under "
            f"Theorems, P2M, and Definitions plus {included}. "
            f"The tree has {classified['lean_files']} .lean files. "
            f"The {len(non_package)} extra .lean files are {extra_names}. "
            f"They are not package modules.{challenge_note}"
        )
    return (
        f"README says {readme_modules} modules. "
        f"Files under Theorems, P2M, and Definitions: {package_dirs}. "
        f"Other .lean files treated as package modules: {included}. "
        f"Those total {package_total}, which does not equal the README count. "
        f"The tree has {classified['lean_files']} .lean files. "
        f"The {len(non_package)} .lean files outside that package count are {extra_names}. "
        f"They are not package modules.{challenge_note}"
    )


def _require_apache(text: str, label: str) -> None:
    head = text[:800]
    missing = [marker for marker in APACHE_MARKERS if marker not in head]
    if missing:
        raise AtlasError(f"{label} is missing an Apache-2.0 header")


def _license_record(web: str, commit: str, path: str, text: str) -> dict[str, str]:
    _require_apache(text, path)
    return {
        "path": path,
        "url": blob_url(web, commit, path),
        "sha256": file_sha256(text),
    }


def _load_json(text: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AtlasError(f"{label} is not JSON") from exc
    if not isinstance(parsed, dict):
        raise AtlasError(f"{label} is not a JSON object")
    return parsed


def _theorem_names(config: dict[str, Any], label: str) -> list[str]:
    names = config.get("theorem_names")
    if not isinstance(names, list) or not names or not all(isinstance(item, str) for item in names):
        raise AtlasError(f"{label} has no theorem names")
    return list(names)


def _commit_meta(repo: Path) -> tuple[str, str]:
    lines = git(repo, "log", "-1", "--format=%cI%n%s").splitlines()
    date = lines[0][:10] if lines and lines[0] else ""
    subject = lines[1] if len(lines) > 1 else ""
    return date, subject


def _top_level_dirs(paths: list[str]) -> list[str]:
    found = {path.split("/", 1)[0] for path in paths if "/" in path}
    return sorted(found)


def resolve_tag(url: str, name: str) -> dict[str, str]:
    """Return the annotated tag object and the commit it peels to."""
    result = run_git(
        ["git", "ls-remote", url, f"refs/tags/{name}*"],
        None,
        "could not read the upstream tag",
    )
    tag_object = ""
    peeled = ""
    for line in result.stdout.splitlines():
        sha, ref = line.split()
        if ref == f"refs/tags/{name}^{{}}":
            peeled = sha
        elif ref == f"refs/tags/{name}":
            tag_object = sha
    if not re.fullmatch(r"[0-9a-f]{40}", tag_object):
        raise AtlasError(f"tag {name} was not found")
    if not peeled:
        peeled = tag_object
    if not re.fullmatch(r"[0-9a-f]{40}", peeled):
        raise AtlasError(f"tag {name} did not peel to a commit")
    return {"name": name, "tag_object": tag_object, "commit": peeled}


def anthropic_join(
    anthropic: dict[str, Any],
    openai_erdos: set[int],
    apn_erdos: set[int],
    other_text: str,
) -> dict[str, Any]:
    """Intersect Anthropic ids with ids already explicit in the other two catalogues."""
    ours = anthropic["identifiers"]
    our_erdos = {int(item) for item in ours["erdos"]}
    other = find_identifiers(other_text)
    shared: list[dict[str, str]] = []
    for number in sorted(our_erdos & (openai_erdos | apn_erdos)):
        shared.append({"kind": "erdos", "id": str(number)})
    for item in sorted(set(ours["oeis"]) & set(other["oeis"])):
        shared.append({"kind": "oeis", "id": item})
    for item in sorted(set(ours["stacks"]) & set(other["stacks"])):
        shared.append({"kind": "stacks", "id": item})
    return {
        "anthropic_identifiers": {
            "erdos": list(ours["erdos"]),
            "oeis": list(ours["oeis"]),
            "stacks": list(ours["stacks"]),
            "method": ours["method"],
        },
        "shared_with_anthropic": shared,
        "anthropic_empty_text": "" if shared else ANTHROPIC_EMPTY_TEXT,
    }


def _zeta_notes(yaml_text: str, tag: dict[str, str], commit: str) -> list[str]:
    for marker in ("Claude", "Ralph Furman", "Levent Alpöge"):
        if marker not in yaml_text:
            raise AtlasError(f"zeta23 formalization.yaml is missing {marker}")
    return [
        f"Subject: {ZETA_SUBJECT}. {NOT_RH}",
        (
            "formalization.yaml says Claude wrote the Lean code. It names Ralph Furman as a reviewer "
            "of the challenge module and Levent Alpöge as an author of the paper."
        ),
        (
            f"Annotated tag {tag['name']} peels to {tag['commit']}. "
            f"File counts here are from {commit}, not from that tag."
        ),
    ]


def _three_notes() -> list[str]:
    return [
        NOT_FORMALIZED_LABEL[0].upper() + NOT_FORMALIZED_LABEL[1:] + ".",
        "No announcement on anthropic.com is recorded for this release.",
    ]


def assemble(
    fm_paths: list[str],
    flt_paths: list[str],
    files: dict[str, str],
    fm_commit: str,
    flt_commit: str,
    tag: dict[str, str],
    fm_date: str,
    fm_subject: str,
    flt_date: str,
    flt_subject: str,
) -> dict[str, Any]:
    """Build the snapshot from path lists and the statement files already fetched."""
    if not re.fullmatch(r"[0-9a-f]{40}", fm_commit) or not re.fullmatch(r"[0-9a-f]{40}", flt_commit):
        raise AtlasError("Anthropic commits must be full shas")
    for key in (
        "fm:LICENSE",
        "fm:zeta23/LICENSE",
        "fm:zeta23/lean-toolchain",
        "fm:zeta23/comparator.json",
        "fm:zeta23/comparator-xiprime.json",
        "fm:zeta23/formalization.yaml",
        "fm:3sum-apsp/LICENSE",
        "fm:3sum-apsp/lean-toolchain",
        "fm:3sum-apsp/README.md",
        "fm:3sum-apsp/comparator-endstatement.json",
        "fm:3sum-apsp/comparator-paperstatements.json",
        "flt:LICENSE",
        "flt:README.md",
        "flt:lean-toolchain",
        "flt:formalization.yaml",
    ):
        if key not in files:
            raise AtlasError(f"Anthropic snapshot is missing {key}")

    skipped = [
        name
        for name in _top_level_dirs(fm_paths)
        if name not in FORMAL_MATH_PROJECTS and name not in IGNORED_TOP_LEVEL
    ]
    if any(path == "percolation" or path.startswith("percolation/") for path in fm_paths):
        if "percolation" not in skipped:
            skipped.append("percolation")
            skipped.sort()

    zeta_paths = [path for path in fm_paths if path.startswith("zeta23/")]
    three_paths = [path for path in fm_paths if path.startswith("3sum-apsp/")]
    zeta_lean = [path for path in zeta_paths if path.endswith(".lean")]
    three_lean = [path for path in three_paths if path.endswith(".lean")]
    if not zeta_lean or not three_lean:
        raise AtlasError("formal-math is missing Lean files for a pinned project")

    headline = _theorem_names(_load_json(files["fm:zeta23/comparator.json"], "comparator.json"), "comparator.json")
    xi_prime = _theorem_names(
        _load_json(files["fm:zeta23/comparator-xiprime.json"], "comparator-xiprime.json"),
        "comparator-xiprime.json",
    )
    end_names = _theorem_names(
        _load_json(files["fm:3sum-apsp/comparator-endstatement.json"], "comparator-endstatement.json"),
        "comparator-endstatement.json",
    )
    paper_names = _theorem_names(
        _load_json(files["fm:3sum-apsp/comparator-paperstatements.json"], "comparator-paperstatements.json"),
        "comparator-paperstatements.json",
    )
    flt_counts = classify_flt(flt_paths)
    if "Theorems/Thm_fermat_last_theorem.lean" not in flt_paths:
        raise AtlasError("Fermat tree is missing Theorems/Thm_fermat_last_theorem.lean")
    modules_match = README_MODULES_RE.search(files["flt:README.md"])
    if modules_match is None:
        raise AtlasError("Fermat README does not state a module count")
    readme_modules = int(modules_match.group(1).replace(",", ""))
    readme_text = files["fm:3sum-apsp/README.md"]
    if "Real inputs" not in readme_text or "Not proved for any machine" not in readme_text:
        raise AtlasError("3sum-apsp README no longer marks real inputs as not proved")
    pair_ceiling = any(path.startswith("zeta23/Zeta23/PairCeiling/") for path in zeta_paths)
    if not pair_ceiling:
        raise AtlasError("zeta23 PairCeiling topic is missing from the tree")

    identifier_text = "\n".join([*fm_paths, *flt_paths, *files.values()])
    identifiers = find_identifiers(identifier_text)
    identifiers["method"] = IDENTIFIER_METHOD

    zeta_toolchain = files["fm:zeta23/lean-toolchain"].strip()
    three_toolchain = files["fm:3sum-apsp/lean-toolchain"].strip()
    flt_toolchain = files["flt:lean-toolchain"].strip()
    flt_yaml = files["flt:formalization.yaml"]
    axiom_match = re.findall(r"propext|Classical\.choice|Quot\.sound", flt_yaml)
    axioms = []
    for name in ("propext", "Classical.choice", "Quot.sound"):
        if name in flt_yaml and name not in axioms:
            axioms.append(name)
    if axioms != ["propext", "Classical.choice", "Quot.sound"]:
        raise AtlasError(f"Fermat formalization.yaml axioms are {axioms or axiom_match}")
    names_comparator = "comparator" in files["flt:README.md"].lower()
    names_nanoda = "nanoda" in files["flt:README.md"].lower()
    if not names_comparator or not names_nanoda:
        raise AtlasError("Fermat README does not name comparator and nanoda")

    zeta_notes = _zeta_notes(files["fm:zeta23/formalization.yaml"], tag, fm_commit)
    root_license = _license_record(FORMAL_MATH_WEB, fm_commit, "LICENSE", files["fm:LICENSE"])
    zeta_license = _license_record(FORMAL_MATH_WEB, fm_commit, "zeta23/LICENSE", files["fm:zeta23/LICENSE"])
    three_license = _license_record(FORMAL_MATH_WEB, fm_commit, "3sum-apsp/LICENSE", files["fm:3sum-apsp/LICENSE"])
    flt_license = _license_record(FLT_WEB, flt_commit, "LICENSE", files["flt:LICENSE"])

    releases = [
        {
            "id": "zeta23",
            "kind": "new-result",
            "kind_label": "New result",
            "title": "More than two thirds of the zeta zeros are simple and on the critical line",
            "statement": (
                f"Lean files deposited upstream for {ZETA_SUBJECT}. {NOT_RH}"
            ),
            "repo": FORMAL_MATH_WEB,
            "commit": fm_commit,
            "commit_date": fm_date,
            "commit_subject": fm_subject,
            "path": "zeta23",
            "tree_url": tree_url(FORMAL_MATH_WEB, fm_commit, "zeta23"),
            "license": "Apache-2.0",
            "license_files": [root_license, zeta_license],
            "lean_toolchain": zeta_toolchain,
            "paper": {
                "id": "2608.13637",
                "title": "More than two thirds of the zeta zeros are simple and on the critical line",
                "url": "https://arxiv.org/abs/2608.13637",
                "v1_submitted": "2026-08-13",
                "v2_submitted": "2026-08-19",
            },
            "announcement": "https://www.anthropic.com/research/riemann-zeta",
            "announcement_date": None,
            "tag": tag,
            "counts": {
                "lean_files": len(zeta_lean),
                "headline_theorems": len(headline),
                "xi_prime_statements": len(xi_prime),
            },
            "headline_theorems": headline,
            "xi_prime_theorems": xi_prime,
            "statement_files": [
                {
                    "path": "zeta23/Challenge.lean",
                    "url": blob_url(FORMAL_MATH_WEB, fm_commit, "zeta23/Challenge.lean"),
                    "role": "headline statements",
                },
                {
                    "path": "zeta23/Challenge/XiPrime.lean",
                    "url": blob_url(FORMAL_MATH_WEB, fm_commit, "zeta23/Challenge/XiPrime.lean"),
                    "role": "xi-prime statements",
                },
            ],
            "scope_notes": zeta_notes,
            "gaps": [
                {
                    "id": "zeta23-pair-ceiling",
                    "status": "NOT IN COMPARATOR",
                    "label": PAIR_CEILING_LABEL,
                }
            ],
        },
        {
            "id": "3sum-apsp",
            "kind": "new-result",
            "kind_label": "New result",
            "title": "Truly subquadratic 3SUM and subcubic APSP",
            "statement": (
                "Lean files deposited upstream for headline claims about word-RAM programs. "
                "Real-number inputs and some running-time claims are not formalized."
            ),
            "repo": FORMAL_MATH_WEB,
            "commit": fm_commit,
            "commit_date": fm_date,
            "commit_subject": fm_subject,
            "path": "3sum-apsp",
            "tree_url": tree_url(FORMAL_MATH_WEB, fm_commit, "3sum-apsp"),
            "license": "Apache-2.0",
            "license_files": [root_license, three_license],
            "lean_toolchain": three_toolchain,
            "paper": {
                "id": "2610.06783",
                "title": (
                    "Truly Subquadratic 3SUM and Truly Subcubic APSP via Triangles "
                    "in Sparse Lopsided Graphs"
                ),
                "url": "https://arxiv.org/abs/2610.06783",
                "v1_submitted": "2026-10-05",
                "v2_submitted": None,
            },
            "announcement": None,
            "announcement_date": None,
            "tag": None,
            "counts": {
                "lean_files": len(three_lean),
                "headline_theorems": len(end_names),
                "paper_statement_theorems": len(paper_names),
            },
            "headline_theorems": end_names,
            "xi_prime_theorems": [],
            "statement_files": [
                {
                    "path": "3sum-apsp/EndStatement.lean",
                    "url": blob_url(FORMAL_MATH_WEB, fm_commit, "3sum-apsp/EndStatement.lean"),
                    "role": "headline statements",
                },
                {
                    "path": "3sum-apsp/comparator-endstatement.json",
                    "url": blob_url(FORMAL_MATH_WEB, fm_commit, "3sum-apsp/comparator-endstatement.json"),
                    "role": "headline comparator configuration",
                },
            ],
            "scope_notes": _three_notes(),
            "gaps": [
                {
                    "id": "3sum-not-formalized",
                    "status": "NOT FORMALIZED",
                    "label": NOT_FORMALIZED_LABEL,
                }
            ],
        },
        {
            "id": "fermat-last-theorem",
            "kind": "formalization",
            "kind_label": "Formalization",
            "title": "Fermat's Last Theorem",
            "statement": (
                "Lean files deposited upstream for Fermat's Last Theorem. "
                "This is a formalization of a known theorem, not a new result."
            ),
            "repo": FLT_WEB,
            "commit": flt_commit,
            "commit_date": flt_date,
            "commit_subject": flt_subject,
            "path": "",
            "tree_url": f"{FLT_WEB}/tree/{flt_commit}",
            "license": "Apache-2.0",
            "license_files": [flt_license],
            "lean_toolchain": flt_toolchain,
            "paper": None,
            "announcement": "https://www.anthropic.com/research/formalizing-fermats-last-theorem",
            "announcement_date": "2026-09-04",
            "tag": None,
            "counts": {
                **flt_counts,
                "readme_modules": readme_modules,
            },
            "headline_theorems": ["fermat_last_theorem"],
            "xi_prime_theorems": [],
            "statement_files": [
                {
                    "path": "Theorems/Thm_fermat_last_theorem.lean",
                    "url": blob_url(FLT_WEB, flt_commit, "Theorems/Thm_fermat_last_theorem.lean"),
                    "role": "theorem statement",
                },
                {
                    "path": "FinalCheck.lean",
                    "url": blob_url(FLT_WEB, flt_commit, "FinalCheck.lean"),
                    "role": "axiom guard",
                },
            ],
            "axioms": axioms,
            "scope_notes": [
                "Formalization of a known theorem, not a new result.",
                (
                    "The README names comparator and nanoda. "
                    "formalization.yaml lists the axioms propext, Classical.choice, and Quot.sound. "
                    + CHECK_WORDING
                ),
            ],
            "gaps": [
                {
                    "id": "flt-module-count",
                    "status": "NOTED",
                    "label": module_count_label(
                        readme_modules,
                        flt_counts,
                        files["flt:README.md"],
                    ),
                }
            ],
        },
    ]
    lean_files = sum(release["counts"]["lean_files"] for release in releases)
    new_results = sum(1 for release in releases if release["kind"] == "new-result")
    formalizations = sum(1 for release in releases if release["kind"] == "formalization")
    source = {
        "id": ANTHROPIC_SOURCE_ID,
        "name": "Anthropic",
        "org": "Anthropic",
        "repo": FORMAL_MATH_WEB,
        "paper": None,
        "license": "Apache-2.0",
        "sync": "tree-snapshot",
        "commit": fm_commit,
        "also": [
            {
                "label": "Fermat's Last Theorem",
                "repo": FLT_WEB,
                "commit": flt_commit,
            }
        ],
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "check_wording": CHECK_WORDING,
        "quotations": list(QUOTATIONS),
        "counts": {
            "releases": len(releases),
            "new_results": new_results,
            "formalizations": formalizations,
            "lean_files": lean_files,
        },
        "identifiers": identifiers,
        "skipped_directories": skipped,
        "releases": releases,
    }
    payload["count_lines"] = count_lines(payload)
    payload["snapshot_digest"] = snapshot_digest(payload)
    assert_anthropic(payload)
    return payload


def assert_anthropic(payload: dict[str, Any]) -> None:
    releases = payload["releases"]
    ids = [release["id"] for release in releases]
    if ids != list(RELEASE_IDS):
        raise AtlasError(f"Anthropic releases are {ids}")
    kinds = [release["kind"] for release in releases]
    if kinds != ["new-result", "new-result", "formalization"]:
        raise AtlasError(f"Anthropic kinds are {kinds}")
    if payload["counts"]["releases"] != 3:
        raise AtlasError("Anthropic release count drifted")
    if payload["counts"]["new_results"] != 2 or payload["counts"]["formalizations"] != 1:
        raise AtlasError("Anthropic kind counts drifted")
    lean_files = sum(release["counts"]["lean_files"] for release in releases)
    if payload["counts"]["lean_files"] != lean_files:
        raise AtlasError("Anthropic Lean file total does not match the releases")
    if payload["count_lines"] != count_lines(payload):
        raise AtlasError("Anthropic count lines drifted")
    if payload["check_wording"] != CHECK_WORDING:
        raise AtlasError("Anthropic check wording drifted")
    if payload["quotations"] != [dict(item) for item in QUOTATIONS]:
        raise AtlasError("Anthropic quotation list drifted")
    for quotation in payload["quotations"]:
        if not quotation.get("text") or not quotation.get("source"):
            raise AtlasError("Anthropic quotation is missing text or a source")
    identifiers = payload["identifiers"]
    if identifiers["method"] != IDENTIFIER_METHOD:
        raise AtlasError("Anthropic identifier method drifted")
    for release in releases:
        if release["license"] != "Apache-2.0" or not release["license_files"]:
            raise AtlasError(f"{release['id']} is missing an Apache-2.0 license link")
        if release["kind"] == "formalization" and release["kind_label"] != "Formalization":
            raise AtlasError("formalization badge label drifted")
        if release["kind"] == "new-result" and release["kind_label"] != "New result":
            raise AtlasError("new-result badge label drifted")
        for gap in release["gaps"]:
            if not gap.get("id") or not gap.get("status") or not gap.get("label"):
                raise AtlasError(f"{release['id']} gap is incomplete")
    by_id = {release["id"]: release for release in releases}
    three_gap = by_id["3sum-apsp"]["gaps"][0]
    if three_gap["status"] != "NOT FORMALIZED" or three_gap["label"] != NOT_FORMALIZED_LABEL:
        raise AtlasError("3sum gap wording drifted")
    if by_id["fermat-last-theorem"]["kind"] != "formalization":
        raise AtlasError("Fermat release is not marked as a formalization")
    fm_commit = payload["source"]["commit"]
    flt_commit = payload["source"]["also"][0]["commit"]
    if fm_commit != PINNED_FORMAL_MATH_COMMIT or flt_commit != PINNED_FLT_COMMIT:
        return
    if payload["skipped_directories"]:
        raise AtlasError(f"pinned formal-math tree has extra directories: {payload['skipped_directories']}")
    if any(identifiers[key] for key in ("erdos", "oeis", "stacks")):
        raise AtlasError(f"pinned Anthropic identifiers are not empty: {identifiers}")
    zeta = by_id["zeta23"]["counts"]
    if (zeta["lean_files"], zeta["headline_theorems"], zeta["xi_prime_statements"]) != (326, 17, 6):
        raise AtlasError(f"pinned zeta23 counts are {zeta}")
    three = by_id["3sum-apsp"]["counts"]
    if (three["lean_files"], three["headline_theorems"]) != (434, 5):
        raise AtlasError(f"pinned 3sum-apsp counts are {three}")
    flt = by_id["fermat-last-theorem"]["counts"]
    if (flt["lean_files"], flt["theorem_files"], flt["proof_files"], flt["definition_files"]) != (
        60478,
        29511,
        29513,
        1450,
    ):
        raise AtlasError(f"pinned Fermat counts are {flt}")
    if by_id["zeta23"]["tag"]["commit"] != PINNED_ZETA_TAG_COMMIT:
        raise AtlasError("pinned v1.0 tag peel drifted")
    if by_id["zeta23"]["lean_toolchain"] != "leanprover/lean4:v4.33.0-rc2":
        raise AtlasError("pinned zeta23 toolchain drifted")
    if by_id["3sum-apsp"]["lean_toolchain"] != "leanprover/lean4:v4.33.1":
        raise AtlasError("pinned 3sum toolchain drifted")
    if by_id["fermat-last-theorem"]["lean_toolchain"] != "leanprover/lean4:v4.33.1":
        raise AtlasError("pinned Fermat toolchain drifted")
    module_label = by_id["fermat-last-theorem"]["gaps"][0]["label"]
    if "(3 more)" in module_label or "Paths outside" in module_label:
        raise AtlasError(f"pinned Fermat module label still mixes the extra files: {module_label}")
    if "not package modules" not in module_label or "FinalCheck.lean" not in module_label:
        raise AtlasError(f"pinned Fermat module label drifted: {module_label}")
    if "zero-density" in by_id["zeta23"]["statement"] or "zero-density" in " ".join(
        by_id["zeta23"]["scope_notes"]
    ):
        raise AtlasError("pinned zeta wording still says zero-density")
    digest = snapshot_digest(payload)
    if not PINNED_ANTHROPIC_DIGEST:
        raise AtlasError(f"fill the pinned Anthropic digest: {digest}")
    if digest != PINNED_ANTHROPIC_DIGEST:
        raise AtlasError(f"pinned Anthropic snapshot digest drifted: {digest}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_anthropic(fm_repo: Path, flt_repo: Path, tag: dict[str, str] | None = None) -> dict[str, Any]:
    fm_commit = git(fm_repo, "rev-parse", "HEAD").strip()
    flt_commit = git(flt_repo, "rev-parse", "HEAD").strip()
    if tag is None:
        tag = resolve_tag(FORMAL_MATH_URL, PINNED_ZETA_TAG)
    fm_date, fm_subject = _commit_meta(fm_repo)
    flt_date, flt_subject = _commit_meta(flt_repo)
    files = {
        "fm:LICENSE": _read(fm_repo / "LICENSE"),
        "fm:zeta23/LICENSE": _read(fm_repo / "zeta23" / "LICENSE"),
        "fm:zeta23/lean-toolchain": _read(fm_repo / "zeta23" / "lean-toolchain"),
        "fm:zeta23/comparator.json": _read(fm_repo / "zeta23" / "comparator.json"),
        "fm:zeta23/comparator-xiprime.json": _read(fm_repo / "zeta23" / "comparator-xiprime.json"),
        "fm:zeta23/formalization.yaml": _read(fm_repo / "zeta23" / "formalization.yaml"),
        "fm:3sum-apsp/LICENSE": _read(fm_repo / "3sum-apsp" / "LICENSE"),
        "fm:3sum-apsp/lean-toolchain": _read(fm_repo / "3sum-apsp" / "lean-toolchain"),
        "fm:3sum-apsp/README.md": _read(fm_repo / "3sum-apsp" / "README.md"),
        "fm:3sum-apsp/comparator-endstatement.json": _read(fm_repo / "3sum-apsp" / "comparator-endstatement.json"),
        "fm:3sum-apsp/comparator-paperstatements.json": _read(
            fm_repo / "3sum-apsp" / "comparator-paperstatements.json"
        ),
        "flt:LICENSE": _read(flt_repo / "LICENSE"),
        "flt:README.md": _read(flt_repo / "README.md"),
        "flt:lean-toolchain": _read(flt_repo / "lean-toolchain"),
        "flt:formalization.yaml": _read(flt_repo / "formalization.yaml"),
    }
    fm_paths = list_paths(fm_repo)
    flt_paths = list_paths(flt_repo)
    for prefix, expected in (("zeta23/", None), ("3sum-apsp/", None)):
        listed = [path for path in fm_paths if path.startswith(prefix) and path.endswith(".lean")]
        on_disk = sorted(
            path.relative_to(fm_repo).as_posix()
            for path in (fm_repo / prefix[:-1]).rglob("*.lean")
            if path.is_file()
        )
        if on_disk != listed:
            raise AtlasError(f"{prefix} checkout does not match the commit tree")
        del expected
    return assemble(
        fm_paths,
        flt_paths,
        files,
        fm_commit,
        flt_commit,
        tag,
        fm_date,
        fm_subject,
        flt_date,
        flt_subject,
    )


def fetch_anthropic(fm_commit: str, flt_commit: str) -> dict[str, Any]:
    tag = resolve_tag(FORMAL_MATH_URL, PINNED_ZETA_TAG)
    with tempfile.TemporaryDirectory(prefix="atlas-anthropic-") as tmp:
        root = Path(tmp)
        fm_repo = root / "formal-math"
        flt_repo = root / "flt"
        materialize_upstream(FORMAL_MATH_URL, fm_commit, fm_repo, FORMAL_MATH_SPARSE_PATHS)
        materialize_upstream(FLT_URL, flt_commit, flt_repo, FLT_SPARSE_PATHS)
        return build_anthropic(fm_repo, flt_repo, tag)


def verify_recorded_anthropic() -> None:
    """Rebuild data/anthropic.json from the commits it names and fail on any difference.

    Each commit must be that repository's HEAD or an ancestor of it. generated_at
    and the snapshot digest field are ignored. A fetch or network failure is an AtlasError.
    """
    recorded = read_json(ANTHROPIC_JSON)
    fm_commit = str(recorded.get("source", {}).get("commit", ""))
    also = recorded.get("source", {}).get("also") or []
    flt_commit = str(also[0].get("commit", "")) if also else ""
    if not re.fullmatch(r"[0-9a-f]{40}", fm_commit) or not re.fullmatch(r"[0-9a-f]{40}", flt_commit):
        raise AtlasError("anthropic.json has no commit sha")
    rebuilt = fetch_anthropic(fm_commit, flt_commit)
    if snapshot_body(recorded) != snapshot_body(rebuilt):
        raise AtlasError(f"anthropic.json differs from commits {fm_commit} and {flt_commit}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-math-sha", default=PINNED_FORMAL_MATH_COMMIT)
    parser.add_argument("--flt-sha", default=PINNED_FLT_COMMIT)
    args = parser.parse_args()
    payload = fetch_anthropic(args.formal_math_sha, args.flt_sha)
    write_json(ANTHROPIC_JSON, payload)
    counts = payload["counts"]
    print(f"wrote {ANTHROPIC_JSON}")
    print(f"digest {payload['snapshot_digest']}")
    print(
        "counts "
        f"releases={counts['releases']} "
        f"lean={counts['lean_files']} "
        f"new={counts['new_results']} "
        f"formalizations={counts['formalizations']}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
