#!/usr/bin/env python3
"""Build the AlphaEvolve snapshot from the pinned upstream tree.

The catalogue rows are the notebook-checked constructions in the tree.
There are no Lean files. Titles for the maths directories are the names
the README uses for those directories. A directory the map does not name
stops the build. Notebook paths are taken from the tree.
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
    claim_word_hits,
    git,
    materialize_upstream,
    read_json,
    write_json,
)

ALPHAEVOLVE_JSON = ROOT / "data" / "alphaevolve.json"
ALPHAEVOLVE_URL = "https://github.com/google-deepmind/alphaevolve.git"
ALPHAEVOLVE_WEB = "https://github.com/google-deepmind/alphaevolve"
ALPHAEVOLVE_SOURCE_ID = "alphaevolve"
PAPER_TODO = "TODO(franrruiz): Add link to paper."
PAPER_NOTE = "The README paper link is still TODO."
PRODUCT_NOTE = "The repository says this is not an official Google product."
CHECK_WORDING = (
    "Constructions checked by notebook. This tree has no Lean files. "
    "This atlas did not run the notebooks."
)
BADGE = "Checked by notebook"
# Names the README uses for each maths directory, in the README's order.
# The set has to equal the directories under maths/. The count is that set.
MATHS_TITLES: tuple[tuple[str, str], ...] = (
    ("circle_packing", "Circle packing"),
    ("erdos_minimum_overlap", "Erdös minimum overlap"),
    ("first_autocorrelation_inequality", "First autocorrelation inequality"),
    ("second_autocorrelation_inequality", "Second autocorrelation inequality"),
    ("third_autocorrelation_inequality", "Third autocorrelation inequality"),
    ("heilbronn_convex", "Heilbronn problem for convex regions"),
    ("heilbronn_triangle", "Heilbronn problem for triangles"),
    ("hexagon_packing", "Hexagon packing"),
    ("kissing", "Kissing numbers"),
    ("max_min_ratio", "Max to min ratio"),
    ("sums_and_differences", "Sums and differences"),
    ("uncertainty_principles", "Uncertainty principles"),
    ("extremal_girth_5", "Extremal girth 5"),
    ("shannon_cycle", "Shannon capacity of cycle graphs"),
    ("cap_sets", "Cap sets"),
)
UNCERTAINTY_NOTEBOOKS = (
    "verification_hermite.ipynb",
    "verification_laguerre.ipynb",
)
OMEGA_NOTEBOOK = "omega/verification.ipynb"
MATMUL_TITLES = {
    "verification_rank.ipynb": "Matrix-multiplication tensor rank",
    "verification_support_rank.ipynb": "Matrix-multiplication tensor support rank",
}
# Path names come from git ls-tree. Only the README and LICENSE blobs are fetched.
ALPHAEVOLVE_SPARSE_PATHS = [
    "/README.md",
    "/LICENSE",
]
APACHE_MARKERS = ("Apache License", "Version 2.0")


def snapshot_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"generated_at", "snapshot_digest"}}


def snapshot_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot_body(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def file_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def blob_url(commit: str, path: str) -> str:
    return f"{ALPHAEVOLVE_WEB}/blob/{commit}/{path}"


def list_paths(repo: Path) -> list[str]:
    output = git(repo, "ls-tree", "-r", "--name-only", "HEAD")
    return [line for line in output.splitlines() if line]


def _commit_meta(repo: Path) -> tuple[str, str]:
    output = git(repo, "log", "-1", "--format=%cs%n%s")
    date, subject = output.split("\n", 1)
    return date.strip(), subject.strip()


def _license_record(commit: str, text: str) -> dict[str, str]:
    if not all(marker in text for marker in APACHE_MARKERS):
        raise AtlasError("AlphaEvolve LICENSE is not Apache-2.0")
    return {
        "path": "LICENSE",
        "url": blob_url(commit, "LICENSE"),
        "sha256": file_sha256(text),
    }


def _notebooks_under(paths: list[str], prefix: str) -> list[str]:
    return sorted(path for path in paths if path.startswith(prefix) and path.endswith(".ipynb"))


def _record(
    record_id: str,
    area: str,
    title: str,
    statement: str,
    notebooks: list[str],
    commit: str,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "anchor": record_id,
        "source": ALPHAEVOLVE_SOURCE_ID,
        "area": area,
        "title": title,
        "statement": statement,
        "notebooks": [
            {"path": path, "url": blob_url(commit, path)}
            for path in notebooks
        ],
        "scope_notes": [
            "Checked by notebook. Not a formal Lean artifact.",
        ],
    }


def _maths_records(paths: list[str], readme: str, commit: str) -> list[dict[str, Any]]:
    directories = sorted(
        {
            path.split("/")[1]
            for path in paths
            if path.startswith("maths/") and path.count("/") >= 2
        }
    )
    expected = [name for name, _title in MATHS_TITLES]
    if directories != sorted(expected):
        raise AtlasError(f"maths directories are {directories}")
    if len(set(expected)) != len(expected):
        raise AtlasError("maths title map repeats a directory")
    records = []
    for directory, title in MATHS_TITLES:
        notebooks = _notebooks_under(paths, f"maths/{directory}/")
        if not notebooks:
            raise AtlasError(f"maths/{directory} has no notebook")
        for path in notebooks:
            if path not in readme:
                raise AtlasError(f"README does not name {path}")
        if directory == "uncertainty_principles":
            names = [Path(path).name for path in notebooks]
            for required in UNCERTAINTY_NOTEBOOKS:
                if required not in names:
                    raise AtlasError(f"uncertainty_principles is missing {required}")
        records.append(
            _record(
                directory.replace("_", "-"),
                "maths",
                title,
                (
                    f"Construction in maths/{directory}. "
                    "The README lists a notebook that checks it. Not a formal Lean artifact."
                ),
                notebooks,
                commit,
            )
        )
    return records


def _omega_record(paths: list[str], readme: str, commit: str) -> dict[str, Any]:
    notebooks = _notebooks_under(paths, "omega/")
    if OMEGA_NOTEBOOK not in notebooks:
        raise AtlasError(f"omega notebooks are {notebooks}")
    if OMEGA_NOTEBOOK not in readme:
        raise AtlasError("README does not name the omega notebook")
    collapsed = re.sub(r"\s+", " ", readme)
    if "matrix multiplication exponent" not in collapsed:
        raise AtlasError("README does not name the matrix multiplication exponent")
    return _record(
        "omega",
        "omega",
        "Claimed bound on the matrix multiplication exponent",
        (
            "Claimed upper bound on the matrix multiplication exponent. "
            "The notebook checks the construction in exact rational arithmetic. "
            "Not a formal Lean artifact."
        ),
        notebooks,
        commit,
    )


def _matmul_records(paths: list[str], readme: str, commit: str) -> list[dict[str, Any]]:
    notebooks = _notebooks_under(paths, "matmul_tensor_decompositions/")
    names = {Path(path).name for path in notebooks}
    for required in MATMUL_TITLES:
        if required not in names:
            raise AtlasError(f"matmul notebooks are missing {required}")
        if f"matmul_tensor_decompositions/{required}" not in readme:
            raise AtlasError(f"README does not name {required}")
    records = []
    for path in notebooks:
        filename = Path(path).name
        title = MATMUL_TITLES.get(filename, filename.removesuffix(".ipynb").replace("_", " "))
        records.append(
            _record(
                f"matmul-{filename.removesuffix('.ipynb').replace('_', '-')}",
                "matmul",
                title,
                (
                    f"Tensor decomposition notebook {path}. "
                    "Checked by notebook. Not a formal Lean artifact."
                ),
                [path],
                commit,
            )
        )
    return records


def alphaevolve_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Card facts for this source. Every number is taken from the snapshot counts."""
    counts = payload["counts"]
    records = int(counts["records"])
    problems = int(counts["maths_problems"])
    notebooks = int(counts["notebooks"])
    lean = int(counts["lean_files"])
    fragment = (
        f"{records} notebook-checked constructions from AlphaEvolve "
        f"({problems} maths problems, {notebooks} notebooks, {lean} Lean files)"
    )
    return {
        "fragment": fragment,
        "tiles": [
            {"value": str(records), "label": "constructions"},
            {"value": str(problems), "label": "maths problems"},
            {"value": str(notebooks), "label": "notebooks"},
            {"value": str(lean), "label": "Lean files"},
        ],
        "detail": "Checked by notebook. Not formal Lean artifacts. The README paper link is still TODO.",
        "bindings": [
            {"value": str(records), "path": ["alphaevolve", "counts", "records"]},
            {"value": str(problems), "path": ["alphaevolve", "counts", "maths_problems"]},
            {"value": str(notebooks), "path": ["alphaevolve", "counts", "notebooks"]},
            {"value": str(lean), "path": ["alphaevolve", "counts", "lean_files"]},
        ],
    }


def assemble(paths: list[str], files: dict[str, str], commit: str, commit_date: str, commit_subject: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AtlasError("AlphaEvolve commit must be a full sha")
    readme = files["README.md"]
    if PAPER_TODO not in readme:
        raise AtlasError("AlphaEvolve README no longer marks the paper link as TODO")
    if "not an official Google product" not in readme:
        raise AtlasError("AlphaEvolve README no longer says it is not an official Google product")
        raise AtlasError("AlphaEvolve README no longer marks the paper link as TODO")
    if "Creative Commons Attribution 4.0" not in readme:
        raise AtlasError("AlphaEvolve README does not name CC-BY 4.0")
    lean = [path for path in paths if path.endswith(".lean")]
    if lean:
        raise AtlasError(f"AlphaEvolve tree has Lean files: {lean[:3]}")
    maths = _maths_records(paths, readme, commit)
    omega = _omega_record(paths, readme, commit)
    matmul = _matmul_records(paths, readme, commit)
    records = [*maths, omega, *matmul]
    notebooks = [item["path"] for record in records for item in record["notebooks"]]
    if len(notebooks) != len(set(notebooks)):
        raise AtlasError("AlphaEvolve notebook paths repeat")
    license_file = _license_record(commit, files["LICENSE"])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "id": ALPHAEVOLVE_SOURCE_ID,
            "name": "AlphaEvolve",
            "org": "Google DeepMind",
            "repo": ALPHAEVOLVE_WEB,
            "paper": None,
            "license": "Apache-2.0 code; CC-BY 4.0 other materials",
            "sync": "tree-snapshot",
            "commit": commit,
        },
        "check_wording": CHECK_WORDING,
        "badge": BADGE,
        "paper_note": PAPER_NOTE,
        "product_note": PRODUCT_NOTE,
        "commit_date": commit_date,
        "commit_subject": commit_subject,
        "license_files": [license_file],
        "counts": {
            "lean_files": 0,
            "maths_problems": len(maths),
            "notebooks": len(notebooks),
            "omega_notebooks": len(omega["notebooks"]),
            "matmul_notebooks": sum(len(record["notebooks"]) for record in matmul),
            "records": len(records),
        },
        "records": records,
    }
    payload["snapshot_digest"] = snapshot_digest(payload)
    assert_alphaevolve(payload, enforce_pin=False)
    return payload


def _reject_claim_words(payload: dict[str, Any]) -> None:
    parts = [
        str(payload.get("check_wording") or ""),
        str(payload.get("badge") or ""),
        str(payload.get("paper_note") or ""),
        str(payload.get("product_note") or ""),
    ]
    for record in payload.get("records") or []:
        if not isinstance(record, dict):
            continue
        parts.append(str(record.get("title") or ""))
        parts.append(str(record.get("statement") or ""))
        for note in record.get("scope_notes") or []:
            parts.append(str(note))
    hits = claim_word_hits("\n".join(parts))
    if hits:
        raise AtlasError(f"AlphaEvolve snapshot uses a claim word: {hits[0]}")


def assert_alphaevolve(
    payload: dict[str, Any],
    pins: dict[str, Any] | None = None,
    *,
    enforce_pin: bool = True,
) -> None:
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("id") != ALPHAEVOLVE_SOURCE_ID:
        raise AtlasError("alphaevolve source is missing")
    if source.get("paper") is not None:
        raise AtlasError("AlphaEvolve paper link is not in the README")
    if payload.get("check_wording") != CHECK_WORDING or payload.get("badge") != BADGE:
        raise AtlasError("AlphaEvolve wording drifted")
    if payload.get("paper_note") != PAPER_NOTE or payload.get("product_note") != PRODUCT_NOTE:
        raise AtlasError("AlphaEvolve paper note drifted")
    counts = payload.get("counts")
    records = payload.get("records")
    if not isinstance(counts, dict) or not isinstance(records, list) or not records:
        raise AtlasError("AlphaEvolve snapshot has no records")
    notebooks = [item["path"] for record in records for item in record.get("notebooks") or []]
    if counts.get("lean_files") != 0:
        raise AtlasError("AlphaEvolve snapshot reports Lean files")
    if counts.get("records") != len(records):
        raise AtlasError("AlphaEvolve record count does not match the rows")
    if counts.get("notebooks") != len(notebooks):
        raise AtlasError("AlphaEvolve notebook count does not match the rows")
    maths = [record for record in records if record.get("area") == "maths"]
    if counts.get("maths_problems") != len(maths):
        raise AtlasError("AlphaEvolve maths count does not match the rows")
    titles = [record.get("title") for record in maths]
    if titles != [title for _name, title in MATHS_TITLES]:
        raise AtlasError(f"AlphaEvolve maths titles are {titles}")
    if payload.get("snapshot_digest") != snapshot_digest(payload):
        raise AtlasError("AlphaEvolve snapshot digest drifted")
    _reject_claim_words(payload)
    if not enforce_pin:
        return
    from atlaslib import load_upstream_pins

    loaded = pins if pins is not None else load_upstream_pins()
    pin = loaded["alphaevolve"]
    if source.get("commit") != pin["commit"]:
        raise AtlasError("alphaevolve checks did not run for the pin in upstream.json")
    digest = snapshot_digest(payload)
    if digest != pin["digest"]:
        raise AtlasError(f"pinned AlphaEvolve snapshot digest drifted: {digest}")


def build_alphaevolve(repo: Path) -> dict[str, Any]:
    commit = git(repo, "rev-parse", "HEAD").strip()
    commit_date, commit_subject = _commit_meta(repo)
    files = {
        "README.md": (repo / "README.md").read_text(encoding="utf-8"),
        "LICENSE": (repo / "LICENSE").read_text(encoding="utf-8"),
    }
    return assemble(list_paths(repo), files, commit, commit_date, commit_subject)


def fetch_alphaevolve(commit: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="atlas-alphaevolve-") as tmp:
        repo = Path(tmp) / "alphaevolve"
        materialize_upstream(ALPHAEVOLVE_URL, commit, repo, ALPHAEVOLVE_SPARSE_PATHS)
        return build_alphaevolve(repo)


def verify_recorded_alphaevolve() -> None:
    """Rebuild data/alphaevolve.json from the commit it names and fail on any difference."""
    recorded = read_json(ALPHAEVOLVE_JSON)
    commit = str(recorded.get("source", {}).get("commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AtlasError("alphaevolve.json has no commit sha")
    rebuilt = fetch_alphaevolve(commit)
    if snapshot_body(recorded) != snapshot_body(rebuilt):
        raise AtlasError(f"alphaevolve.json differs from commit {commit}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    from atlaslib import load_upstream_pins

    pins = load_upstream_pins()
    parser.add_argument("--sha", default=pins["alphaevolve"]["commit"])
    args = parser.parse_args()
    payload = fetch_alphaevolve(args.sha)
    write_json(ALPHAEVOLVE_JSON, payload)
    counts = payload["counts"]
    print(f"wrote {ALPHAEVOLVE_JSON}")
    print(f"digest {payload['snapshot_digest']}")
    print(
        "counts "
        f"records={counts['records']} "
        f"maths={counts['maths_problems']} "
        f"notebooks={counts['notebooks']} "
        f"lean={counts['lean_files']}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
