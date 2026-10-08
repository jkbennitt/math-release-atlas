#!/usr/bin/env python3
"""Fail the build on drifted counts, unsourced tags, or overclaims."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import yaml

from atlaslib import (
    CAUTIONS_JSON,
    CURATED_DIR,
    FAMILIES_JSON,
    REQUIRED_CAUTIONS,
    UPSTREAM_JSON,
    AtlasError,
    assert_counts,
    check_authored,
    check_dist,
    denylist_hit,
    load_cautions,
    parse_contents,
    parse_slug_date,
    plainify,
    read_json,
    scan_overclaims,
    validate_curated_file,
)


def check_source() -> list[str]:
    failures: list[str] = []
    if not UPSTREAM_JSON.is_file() or not FAMILIES_JSON.is_file():
        return ["generated data files are missing"]
    try:
        load_cautions(CAUTIONS_JSON)
        assert_counts(read_json(UPSTREAM_JSON))
        assert_counts(read_json(FAMILIES_JSON))
    except AtlasError as exc:
        failures.append(str(exc))
    failures.extend(check_authored())
    return failures


def expect_error(label: str, func) -> str | None:
    try:
        func()
    except AtlasError:
        return None
    return f"self-test did not fail: {label}"


def self_test() -> list[str]:
    failures: list[str] = []
    sample = plainify(
        "Dirichlet <i>L</i>-function $`\\zeta(s)`$ in $`\\Re s\\gt 7/8`$, "
        "and SL<sub><i>n</i></sub>."
    )
    if sample != "Dirichlet L-function ζ(s) in Re s > 7/8, and SLₙ.":
        failures.append(f"plainify returned {sample!r}")
    title = plainify(r"$`\mathsf L=\mathsf{RL}=\mathsf{BPL}`$").rstrip(".")
    if title != "L=RL=BPL":
        failures.append(f"math title returned {title!r}")
    if parse_slug_date("Example-September-23-2026") != "2026-09-23":
        failures.append("month date parse failed")
    if parse_slug_date("Tangent-flow-uniqueness-2026-09-24") != "2026-09-24":
        failures.append("iso date parse failed")
    contents = """
**010. Parentheses.** A filling bound.

</td>
</tr>
<td>

&emsp;[Sharp integral fillings in CAT(0) spaces](preprints/Sharp-integral-fillings-in-CAT(0)-spaces-September-23-2026/paper.pdf)

Abstract with ABSTRACT-MARKER that must stay out of the summary.
"""
    parsed = parse_contents(contents)
    if len(parsed) != 1 or parsed[0]["manuscripts"][0]["slug"].endswith("2026") is False:
        failures.append("CAT(0) manuscript link was not parsed")
    slug = parsed[0]["manuscripts"][0]["slug"]
    if "CAT(0)" not in slug:
        failures.append(f"slug lost parentheses: {slug}")
    if "ABSTRACT-MARKER" in parsed[0]["upstream_summary"]:
        failures.append("summary included the manuscript abstract")
    for text in REQUIRED_CAUTIONS.values():
        if scan_overclaims(text, "caution"):
            failures.append(f"caution was flagged: {text}")
    for family_id in ("003", "376"):
        extended = REQUIRED_CAUTIONS[family_id].rstrip(".") + " and it is solved."
        if not scan_overclaims(extended, "caution"):
            failures.append(f"extended caution was not flagged: {extended}")
    flagged = [
        "The Riemann Hypothesis is solved.",
        "The Riemann Hypothesis is not solved.",
        "This is not a proof of the Riemann Hypothesis.",
        "Never mind the skeptics; Navier-Stokes is cracked.",
        "RH proved.",
        "We resolved the Clay problem.",
        "The Millennium problem is settled.",
        "Navier–Stokes has been solved.",
        "proving the quasi-Riemann hypothesis.",
        "It is not a small result: the Riemann Hypothesis is solved.",
        "SOLVED the riemann hypothesis.",
        "Navier Stokes cracked.",
        "The Riemann\nHypothesis is solved.",
        "The Riemann Hypothesis is proven.",
        "There is a proof for the Riemann Hypothesis.",
        "We disprove Navier-Stokes.",
        "This disproves the Clay problem.",
        "The Millennium problem was disproved.",
        "RH is established.",
        "This establishes the Riemann Hypothesis.",
        "A solution to the Riemann Hypothesis.",
        "A solution of Navier-Stokes.",
        "R.H. is solved.",
        "The R.H. is proven.",
        "This is not a solution of the Riemann Hypothesis.",
    ]
    for text in flagged:
        if not scan_overclaims(text, "sample"):
            failures.append(f"overclaim was not flagged: {text}")
    allowed_sentence = "The Riemann Hypothesis is solved."
    if scan_overclaims(allowed_sentence, "sample", extra_allowed={allowed_sentence}):
        failures.append("exact allowlisted sentence was flagged")
    if not scan_overclaims(allowed_sentence.rstrip(".") + " today.", "sample", extra_allowed={allowed_sentence}):
        failures.append("near-copy of an allowlisted sentence was not flagged")
    allowed = [
        "This is not the Riemann Hypothesis.",
        "The Riemann Hypothesis remains open.",
        "The Riemann Hypothesis is unsolved.",
        "The Riemann Hypothesis is unproven.",
        "R.H. remains open.",
        "A linear system was solved.",
        "The lemma is proven.",
    ]
    for text in allowed:
        if scan_overclaims(text, "sample"):
            failures.append(f"allowed sentence was flagged: {text}")
    hidden = "".join(chr(code) for code in (102, 117, 115, 105, 111, 110))
    device = "".join(chr(code) for code in (115, 117, 112, 101, 114, 99, 111, 110, 100, 117, 99, 116, 111, 114))
    generated = (
        hidden,
        hidden + "s",
        device,
        device + "s",
        device[:-2] + "ing",
        device + "2223",
        f"{device}-2223",
        f"tc-{device}-2223",
        device[:5] + "-" + device[5:],
    )
    for sample in generated:
        if not denylist_hit(sample):
            failures.append("denylist token was not flagged")
    if denylist_hit("advection-diffusion equation"):
        failures.append("a neighboring token matched the denylist")

    def missing_source() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [{"tag": "plasma-kinetic", "why": "A kinetic model."}],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def solved_curated() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "003.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "003",
                        "lenses": [
                            {
                                "tag": "computation-hardness",
                                "why": "The Riemann Hypothesis is solved.",
                                "source": "no",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def negated_curated() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "003.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "003",
                        "lenses": [
                            {
                                "tag": "computation-hardness",
                                "why": "This is not a proof of the Riemann Hypothesis.",
                                "source": "no",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def ordinary_solved() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [
                            {
                                "tag": "plasma-kinetic",
                                "why": "A linear system was solved.",
                                "source": "Upstream family summary for 362.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    message = expect_error("missing source", missing_source)
    if message:
        failures.append(message)
    message = expect_error("curated solved", solved_curated)
    if message:
        failures.append(message)
    message = expect_error("curated negated proof", negated_curated)
    if message:
        failures.append(message)
    try:
        ordinary_solved()
    except AtlasError as exc:
        failures.append(f"ordinary solved sentence was rejected: {exc}")
    if not CURATED_DIR.is_dir():
        failures.append("curated directory is missing")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true", help="Check generated data and authored text.")
    parser.add_argument("--dist", type=Path, help="Check built HTML.")
    parser.add_argument("--self-test", action="store_true", help="Run guard fixtures.")
    args = parser.parse_args()
    if not (args.source or args.dist or args.self_test):
        args.source = True
        args.self_test = True
    failures: list[str] = []
    if args.self_test:
        failures.extend(self_test())
    if args.source:
        failures.extend(check_source())
    if args.dist:
        failures.extend(check_dist(args.dist))
    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    print("checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
