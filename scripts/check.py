#!/usr/bin/env python3
"""Fail the build on drifted counts, unsourced tags, or overclaims."""

from __future__ import annotations

import argparse
import ast
import inspect
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import atlaslib
from atlaslib import (
    CAUTIONS_JSON,
    COMMUNITY_STATUSES,
    COMMUNITY_STATUS_FILE,
    CURATED_DIR,
    FAMILIES_JSON,
    REQUIRED_CAUTIONS,
    ROOT,
    UPSTREAM_JSON,
    AtlasError,
    assert_counts,
    attach_citations,
    check_authored,
    check_dist,
    denylist_hit,
    exempt_upstream_text,
    assert_merged_catalogue,
    assert_sha_is_ancestor,
    assert_upstream_digest,
    ensure_ancestor_of_origin_head,
    approval_mismatches,
    exempt_index_rows,
    load_cautions,
    load_community_schema,
    load_curated,
    load_status_approvals,
    materialize_upstream,
    merge_data,
    parse_contents,
    parse_slug_date,
    plainify,
    read_json,
    require_upstream_ancestor,
    run_git,
    scan_overclaims,
    strip_upstream_quotes,
    validate_curated_file,
    verify_recorded_upstream,
)
from sync import resolve_remote_sha


def check_source() -> list[str]:
    failures: list[str] = []
    if not UPSTREAM_JSON.is_file() or not FAMILIES_JSON.is_file():
        return ["generated data files are missing"]
    try:
        cautions = load_cautions(CAUTIONS_JSON)
        curated = load_curated(CURATED_DIR)
        upstream = read_json(UPSTREAM_JSON)
        families = read_json(FAMILIES_JSON)
        assert_counts(upstream)
        assert_upstream_digest(upstream)
        assert_counts(families)
        assert_merged_catalogue(upstream, families, curated, cautions)
    except AtlasError as exc:
        failures.append(str(exc))
        failures.extend(check_authored())
        return failures
    for item in curated.values():
        for lens in item["lenses"]:
            if not lens["source"].strip():
                failures.append(f"{item['id']} lens {lens['tag']} is missing a source")
    failures.extend(check_status_vocabulary())
    failures.extend(check_status_approvals(curated))
    failures.extend(check_codeowners())
    failures.extend(check_sync_does_not_write_status())
    failures.extend(check_upstream_text_is_shown())
    failures.extend(check_authored())
    return failures


def check_upstream_text_is_shown() -> list[str]:
    """Upstream summaries and manuscript titles stay on the page."""
    failures: list[str] = []
    for relative in (
        "src/pages/f/[id].astro",
        "src/pages/index.astro",
        "src/lib/atlas.ts",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "withheld" in text or "not shown on this page" in text:
            failures.append(f"{relative} hides upstream text")
    if "withheld" in (ROOT / "scripts" / "atlaslib.py").read_text(encoding="utf-8"):
        failures.append("scripts/atlaslib.py hides upstream text")
    if "withheld" in FAMILIES_JSON.read_text(encoding="utf-8"):
        failures.append("families.json hides upstream text")
    return failures


def check_status_approvals(curated: dict) -> list[str]:
    try:
        approvals = load_status_approvals(atlaslib.STATUS_APPROVALS_FILE)
    except AtlasError as exc:
        return [str(exc)]
    return approval_mismatches(curated, approvals)


def check_codeowners() -> list[str]:
    path = ROOT / ".github" / "CODEOWNERS"
    if not path.is_file():
        return ["CODEOWNERS is missing"]
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    if "data/curated/**" not in text or "@jkbennitt" not in text:
        failures.append("CODEOWNERS does not assign data/curated to @jkbennitt")
    return failures


def check_status_vocabulary() -> list[str]:
    failures: list[str] = []
    try:
        load_community_schema(COMMUNITY_STATUS_FILE)
    except AtlasError as exc:
        failures.append(str(exc))
    lenses = (ROOT / "src" / "lib" / "lenses.ts").read_text(encoding="utf-8")
    for status in sorted(COMMUNITY_STATUSES):
        if f'"{status}"' not in lenses:
            failures.append(f"lenses.ts is missing community status {status}")
    for retired in ("community-confirmed", "broken"):
        if f'"{retired}"' in lenses:
            failures.append(f"lenses.ts still names retired status {retired}")
    return failures


def check_sync_does_not_write_status() -> list[str]:
    """The weekly sync may refresh the catalogue. It must not author a community status."""
    sync = (ROOT / "scripts" / "sync.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8")
    failures: list[str] = []
    if "data/curated" in workflow:
        failures.append("sync workflow touches data/curated")
    if "git add data/upstream.json data/families.json" not in workflow:
        failures.append("sync workflow no longer limits the commit to generated catalogue files")
    for source, label in ((sync, "sync.py"), (workflow, "sync.yml")):
        if "community" in source:
            failures.append(f"{label} names community status")
        for status in sorted(COMMUNITY_STATUSES):
            if status in source:
                failures.append(f"{label} names community status {status}")
    return failures


def _calls_named(func, name: str) -> bool:
    tree = ast.parse(inspect.getsource(func))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        ident = called.id if isinstance(called, ast.Name) else called.attr if isinstance(called, ast.Attribute) else ""
        if ident == name:
            return True
    return False


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "atlas",
        "GIT_AUTHOR_EMAIL": "atlas@example.com",
        "GIT_COMMITTER_NAME": "atlas",
        "GIT_COMMITTER_EMAIL": "atlas@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def ancestry_self_test() -> list[str]:
    """A commit that is not on origin HEAD fails the same check CI runs.

    The fixture is a local origin, so the negative case does not use the network.
    Guard still calls ensure_ancestor_of_origin_head, which fetches origin HEAD
    and runs git merge-base --is-ancestor.
    """
    failures: list[str] = []
    if not _calls_named(verify_recorded_upstream, "materialize_upstream"):
        failures.append("upstream verifier does not call materialize_upstream")
    if not _calls_named(materialize_upstream, "ensure_ancestor_of_origin_head"):
        failures.append("upstream verifier does not call the ancestry check")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed = root / "seed"
        seed.mkdir()
        _git(seed, "init", "-b", "main")
        (seed / "note").write_text("ancestor\n", encoding="utf-8")
        _git(seed, "add", "note")
        _git(seed, "commit", "-m", "ancestor")
        ancestor = _git(seed, "rev-parse", "HEAD")
        (seed / "note").write_text("head\n", encoding="utf-8")
        _git(seed, "add", "note")
        _git(seed, "commit", "-m", "head")
        head = _git(seed, "rev-parse", "HEAD")
        origin = root / "origin.git"
        _git(root, "clone", "--bare", str(seed), str(origin))
        other = root / "other"
        other.mkdir()
        _git(other, "init", "-b", "main")
        (other / "note").write_text("fork\n", encoding="utf-8")
        _git(other, "add", "note")
        _git(other, "commit", "-m", "fork")
        outsider = _git(other, "rev-parse", "HEAD")
        client = root / "client"
        _git(root, "clone", "--no-checkout", str(origin), str(client))
        _git(client, "remote", "add", "other", str(other))
        _git(client, "fetch", "other")
        try:
            ensure_ancestor_of_origin_head(client, outsider)
        except AtlasError as exc:
            if "not an ancestor" not in str(exc):
                failures.append(f"non-ancestor error was {exc}")
        else:
            failures.append("a non-ancestor commit was accepted")
        try:
            ensure_ancestor_of_origin_head(client, ancestor)
            ensure_ancestor_of_origin_head(client, head)
        except AtlasError as exc:
            failures.append(f"an ancestor of origin HEAD was rejected: {exc}")
        try:
            assert_sha_is_ancestor(client, outsider, "FETCH_HEAD")
        except AtlasError:
            pass
        else:
            failures.append("assert_sha_is_ancestor accepted a non-ancestor")
        try:
            require_upstream_ancestor(str(origin), outsider)
        except AtlasError as exc:
            if "not an ancestor" not in str(exc):
                failures.append(f"sync ancestry error was {exc}")
        else:
            failures.append("require_upstream_ancestor accepted a non-ancestor")
        try:
            require_upstream_ancestor(str(origin), ancestor)
        except AtlasError as exc:
            failures.append(f"require_upstream_ancestor rejected an ancestor: {exc}")
        missing = root / "missing.git"
        try:
            run_git(
                ["git", "clone", "--no-checkout", str(missing), str(root / "dest")],
                None,
                "could not fetch upstream",
            )
        except AtlasError as exc:
            message = str(exc)
            if "\n" in message or "Traceback" in message:
                failures.append(f"fetch failure was not one line: {message!r}")
        else:
            failures.append("a missing remote did not fail")
        try:
            resolve_remote_sha(str(root / "no-such.git"), None)
        except AtlasError as exc:
            message = str(exc)
            if "\n" in message or "Traceback" in message:
                failures.append(f"ls-remote failure was not one line: {message!r}")
        else:
            failures.append("ls-remote against a missing remote did not fail")
        called: list[str] = []
        original = atlaslib.ensure_ancestor_of_origin_head

        def spy(repo: Path, sha: str) -> None:
            called.append(sha)
            raise AtlasError("ancestry-check-called")

        atlaslib.ensure_ancestor_of_origin_head = spy
        try:
            try:
                materialize_upstream(str(origin), ancestor, root / "fresh")
            except AtlasError as exc:
                if "ancestry-check-called" not in str(exc):
                    failures.append(f"ancestry spy raised {exc}")
            else:
                failures.append("materialize_upstream returned without the ancestry check")
            if not called:
                failures.append("upstream verifier did not call the ancestry check")
        finally:
            atlaslib.ensure_ancestor_of_origin_head = original
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
    # Phrases the sentence check rejected on main at 32c16fa2. Nothing here may pass.
    main_flagged = (
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
        "Riemann's hypothesis is confirmed.",
        "Riemann's hypothesis is disproven.",
        "The Riemann Hypothesis was disproven.",
        "RH: proof complete.",
        "RH: proof complete",
        "We solved the Navier-Stokes equations.",
        "Navier-Stokes smoothness is proven.",
        "Global regularity of the Navier-Stokes equations is proven.",
        "Navier-Stokes blow-up is settled.",
        "The scheme proves a Navier-Stokes regularity estimate.",
        "RH is true.",
        "RH holds.",
        "The Riemann Hypothesis is now a theorem.",
        "We verify RH.",
        "RH follows.",
        "Our Navier–Stokes solver proves global regularity.",
        "We prove Navier–Stokes energy inequality implies global regularity.",
        "Navier–Stokes bounds settle the regularity question.",
        "The Riemann-Hypothesis is solved.",
        "Millennium-problem solved.",
        "We won the Clay prize.",
        "We show RH.",
        "We demonstrate the Riemann Hypothesis.",
        "RH is a theorem.",
        "RH is correct.",
        "RH has been shown.",
        "Navier–Stokes estimates prove blow up",
        "Navier–Stokes estimates prove blow–up",
        "We obtain RH",
        "We obtained the Riemann Hypothesis.",
        "We are obtaining RH.",
        "Riemann hypothesis: done",
        "Global smooth solutions of Navier-Stokes are proven.",
        "We solved Navier–Stokes flows.",
        "Navier–Stokes flows are solved.",
        "This settles Navier–Stokes flows.",
        "We prove Navier–Stokes flows exist globally.",
        "We crack Navier–Stokes flows.",
        "Navier–Stokes flows: proof complete.",
        "Navier–Stokes energy bounds for smooth data are proven and solve the problem.",
        "Navier–Stokes flows show turbulence",
        "We prove a Navier-Stokes energy inequality for smooth data.",
    )
    flagged = [
        *main_flagged,
        "A resolution of RH.",
        "Navier–Stokes: the proof.",
        "Navier–Stokes solution.",
        "We finish the Millennium problem.",
        "complete proof of RH",
        "RH: a complete proof.",
        "Navier–Stokes: a complete proof.",
        "A complete proof of the Millennium problem.",
        "A complete proof of the Clay problem.",
        "Navier–Stokes estimates: complete proof.",
        "Navier–Stokes solution: complete",
        "a full solution to RH",
        "the RH proof is complete",
        "RH proof.",
        "Proof: RH.",
        "Solution to RH.",
        "Solutions to RH.",
        "RH's proof.",
        "Our solution to RH.",
        "Complete solution of Navier–Stokes.",
        "Navier–Stokes solution is complete.",
        "Navier–Stokes global regularity: solution.",
        "A proof of the long-open conjecture known as the Riemann Hypothesis.",
        "A numerical proof of RH.",
        "Weak solution of the Riemann hypothesis.",
        "A disproof of RH.",
        "The lemma proof of RH.",
        "An approximate solution of the Clay problem.",
        "Strong solution of the Millennium problem.",
        "A solution to NavierStokes.",
        "RH disproof.",
        "RH disproofs.",
        "RH: proof scheme.",
        "proof of the R H",
        "A solution, long sought by many, to Navier–Stokes.",
        "NavierStokes solution",
        "A numerical proof of Navier–Stokes global regularity.",
        "Weak solutions of Navier–Stokes exist globally and are smooth.",
        "Weak solutions of Navier–Stokes: global regularity and smoothness.",
        "A numerical solution of Navier–Stokes gives a counterproof of blow-up.",
        "Numerical solution of the Navier–Stokes existence and smoothness problem.",
        "A weak solution of Navier–Stokes well-posedness.",
        "A numerical disproof of Navier–Stokes.",
        "Navier–Stokes numerical proof of the conjecture.",
        "Numerical solution of the Navier–Stokes problem.",
        "Numerical solution of Navier–Stokes is foolproof of the calculation.",
    ]
    for text in main_flagged:
        if not scan_overclaims(text, "main"):
            failures.append(f"main phrase was not flagged: {text}")
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
        "We prove a Navier-Stokes energy inequality.",
        "We prove a Navier–Stokes energy inequality.",
        "Navier–Stokes energy inequality.",
        "The scheme proves a Navier-Stokes approximation.",
        "Our Navier–Stokes solver proves an energy inequality.",
        "The lemma is a theorem.",
        "We show a bound.",
        "Navier–Stokes energy inequality for smooth data.",
        "Navier–Stokes energy inequality",
        "A complete proof of the lemma.",
        "A resolution of the linear system.",
        "A Navier–Stokes solution scheme",
        "numerical solution of Navier–Stokes",
        "The Navier–Stokes solution operator is bounded",
        "Weak solutions of Navier–Stokes",
        "Leray solutions of the Navier–Stokes equations",
        "A proof assistant checked the RH-type estimate.",
        "Proof of the lemma uses the Navier–Stokes energy inequality.",
        "mild solutions of Navier–Stokes",
        "strong solution of the Navier-Stokes equations",
        "approximate solution of Navier–Stokes",
    ]
    for text in allowed:
        if scan_overclaims(text, "sample"):
            failures.append(f"allowed sentence was flagged: {text}")
    if len(main_flagged) != 67:
        failures.append(f"main phrase list has {len(main_flagged)} entries")
    if len(allowed) != 28:
        failures.append(f"must-pass phrase list has {len(allowed)} entries")

    def why_overclaim(text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [
                            {
                                "tag": "plasma-kinetic",
                                "why": text,
                                "source": "A neutral source string for the regression.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    for text in flagged:
        message = expect_error(f"why overclaim {text}", lambda text=text: why_overclaim(text))
        if message:
            failures.append(message)
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
    stem = "".join(chr(code) for code in (102, 117, 115, 105, 111, 110))
    after_many = "".join(chr(code) for code in (99, 97, 116, 101, 103, 111, 114, 105, 101, 115))
    after_one = "".join(chr(code) for code in (99, 97, 116, 101, 103, 111, 114, 121))
    before = "".join(chr(code) for code in (99, 111, 110, 110, 101, 115))
    warm = "".join(chr(code) for code in (114, 111, 111, 109))
    degree = "".join(
        chr(code)
        for code in (116, 101, 109, 112, 101, 114, 97, 116, 117, 114, 101)
    )
    short = "".join(chr(code) for code in (116, 101, 109, 112))
    compact = "".join(chr(code) for code in (108, 107))
    power = "".join(chr(code) for code in (112, 111, 119, 101, 114))
    allowed_phrases = (
        f"{stem} {after_many}",
        f"{stem} {after_one}",
        f"{before} {stem}",
        f"{stem}-{after_many}",
        f"{before}-{stem}",
        f"{stem}{after_many}",
    )
    for phrase in allowed_phrases:
        if denylist_hit(phrase):
            failures.append("a math compound containing the stem was flagged")
    denied_phrases = (
        f"{warm}-{degree}",
        f"{warm} {degree}",
        f"{warm}{degree}",
        f"{warm}-{short}",
        f"{warm} {short}",
        f"{warm}{short}",
        f"{compact}-99",
        f"{compact}99",
        f"{before} {stem} {power}",
        stem,
    )
    for phrase in denied_phrases:
        if not denylist_hit(phrase):
            failures.append("a denylist compound was not flagged")
    upstream_sentence = (
        "Proves that every Dirichlet L-function is zero-free in Re s > 7/8, "
        "resolving the quasi-Riemann hypothesis."
    )
    if not scan_overclaims(upstream_sentence, "upstream"):
        failures.append("an upstream-style claim sentence was not flagged")
    quoted = (
        f'<blockquote data-upstream="summary">{upstream_sentence}</blockquote>'
        "<p>The lemma is proven.</p>"
    )
    if not scan_overclaims(quoted, "page"):
        failures.append("an upstream quotation that is not a title was not flagged")
    # Rendered result of a template expression {"RH is " + "pro" + "ven."}.
    rendered_claim = '<p data-upstream="summary">RH is proven.</p>'
    if not scan_overclaims(rendered_claim, "template"):
        failures.append("a template-built claim inside an upstream element was not flagged")
    if not scan_overclaims(exempt_upstream_text(rendered_claim, {"The Riemann Hypothesis", "001"}), "template"):
        failures.append("a template-built claim was treated as an upstream title")
    exact_title = '<h1 data-upstream="title">RH is proven.</h1>'
    if scan_overclaims(exempt_upstream_text(exact_title, {"RH is proven.", "001"}), "template"):
        failures.append("an exact upstream title was flagged")
    exact_summary = (
        "Proves that every Dirichlet L-function is zero-free in Re s > 7/8, "
        "resolving the quasi-Riemann hypothesis."
    )
    summary_html = f'<blockquote data-upstream="summary">{exact_summary}</blockquote>'
    if scan_overclaims(exempt_upstream_text(summary_html, {exact_summary, "003"}), "template"):
        failures.append("an exact upstream summary was flagged")
    wrapped_img = (
        f'<blockquote data-upstream="summary"><img alt="RH is proven.">{exact_summary}</blockquote>'
    )
    exempted_img = exempt_upstream_text(wrapped_img, {exact_summary, "003"})
    if 'alt="RH is proven."' not in exempted_img or "Dirichlet" in exempted_img:
        failures.append("exemption blanked an image alt or left summary text")
    if not scan_overclaims(exempted_img, "template"):
        failures.append("an image alt inside an exempt summary was not flagged")
    wrapped_span = (
        '<blockquote data-upstream="summary">'
        f'<span title="RH is proven.">{exact_summary}</span></blockquote>'
    )
    exempted_span = exempt_upstream_text(wrapped_span, {exact_summary, "003"})
    if 'title="RH is proven."' not in exempted_span or "Dirichlet" in exempted_span:
        failures.append("exemption blanked a descendant title or left summary text")
    if not scan_overclaims(exempted_span, "template"):
        failures.append("a title attribute inside an exempt summary was not flagged")
    titled_summary = (
        f'<blockquote data-upstream="summary" title="RH is proven.">{exact_summary}</blockquote>'
    )
    exempted_title = exempt_upstream_text(titled_summary, {exact_summary, "003"})
    if 'title="RH is proven."' not in exempted_title or "Dirichlet" in exempted_title:
        failures.append("exemption blanked a title on the summary element or left summary text")
    if not scan_overclaims(exempted_title, "template"):
        failures.append("a title on an exempt summary element was not flagged")
    commented_summary = (
        f'<blockquote data-upstream="summary">{exact_summary}<!-- RH is proven. --></blockquote>'
    )
    exempted_comment = exempt_upstream_text(commented_summary, {exact_summary, "003"})
    if "<!-- RH is proven. -->" not in exempted_comment or "Dirichlet" in exempted_comment:
        failures.append("exemption dropped an HTML comment or left summary text")
    if not scan_overclaims(exempted_comment, "template"):
        failures.append("an HTML comment inside an exempt summary was not flagged")
    manuscript_title = "The Quasi-Riemann Hypothesis (alternate 11/12 proof)"
    manuscript_html = f'<a data-upstream="manuscript">{manuscript_title}</a>'
    if scan_overclaims(exempt_upstream_text(manuscript_html, {manuscript_title, "003"}), "template"):
        failures.append("an exact manuscript title was flagged")
    authored_claim = "<p>RH: proof complete.</p>"
    if not scan_overclaims(strip_upstream_quotes(authored_claim), "page"):
        failures.append("an authored claim in HTML was not flagged")
    marked = f'<h1 data-upstream="title">{stem}</h1><p>Hello.</p>'
    if not denylist_hit(marked):
        failures.append("a denylist token inside an upstream quotation was ignored")
    if not denylist_hit(strip_upstream_quotes(f"<p>{warm}-{degree}</p>")):
        failures.append("an authored denylist compound in HTML was not flagged")
    for attribute in (
        '<img alt="RH is solved">',
        '<a title="The Riemann Hypothesis is solved">x</a>',
        '<meta name="description" content="RH: proof complete">',
        '<span aria-label="We show RH">x</span>',
        "<input placeholder='RH is correct'>",
        "<img alt=RH-is-solved>",
        '<p aria-description="We obtain RH">x</p>',
        '<span data-note="Riemann hypothesis: done">x</span>',
    ):
        if not scan_overclaims(attribute, "attribute"):
            failures.append(f"a claim in an HTML attribute was not flagged: {attribute}")
    catalogue_attr = '<tr data-title="The Riemann Hypothesis is solved."><td>The lemma is proven.</td></tr>'
    if not scan_overclaims(catalogue_attr, "attribute"):
        failures.append("a claim in a data-title attribute was not flagged")
    graph_attr = '<svg data-title="The Riemann Hypothesis is proven."></svg>'
    if not scan_overclaims(graph_attr, "graph"):
        failures.append("a graph data-title claim was not flagged")
    exact_title = "The Riemann Hypothesis is proven."
    own_row = f'<tr id="f-001" data-title="{exact_title}"><td>The lemma is proven.</td></tr>'
    if scan_overclaims(exempt_index_rows(own_row, [{"id": "001", "title": exact_title}]), "row"):
        failures.append("an exact upstream title on its own row was flagged")
    forged_row = f'<tr id="f-002" data-title="{exact_title}"><td>The lemma is proven.</td></tr>'
    if not scan_overclaims(exempt_index_rows(forged_row, [{"id": "002", "title": "A different title"}]), "row"):
        failures.append("a forged data-title on another row was not flagged")
    sort_attr = '<th data-sort="title">Result</th>'
    if scan_overclaims(sort_attr, "attribute"):
        failures.append("a data-sort value was flagged")
    soft = chr(0x00AD)
    hidden_char = chr(0x200B)
    if not scan_overclaims(f"R{hidden_char}H is solved.", "normalized"):
        failures.append("a zero-width character hid a claim")
    if not scan_overclaims(f"Riem{soft}ann Hypothesis is solved.", "normalized"):
        failures.append("a soft hyphen hid a claim")
    fullwidth = f"{chr(0xFF32)}{chr(0xFF28)} is solved."
    if not scan_overclaims(fullwidth, "normalized"):
        failures.append("a compatibility character hid a claim")
    if not denylist_hit(stem[:3] + hidden_char + stem[3:]):
        failures.append("a zero-width character hid a denylist token")
    if not denylist_hit(stem[:3] + soft + stem[3:]):
        failures.append("a soft hyphen hid a denylist token")
    failures.extend(ancestry_self_test())

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

    def bad_evidence_url() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [
                            {
                                "tag": "plasma-kinetic",
                                "why": "A kinetic model.",
                                "source": "Upstream family summary for 362.",
                            }
                        ],
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": "notes/local.md",
                                    "date": "2026-10-08",
                                    "note": "A short note.",
                                }
                            ],
                        },
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
    def status_without_evidence() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {"status": "independently-checked", "evidence": []},
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def status_with_evidence() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "disputed",
                            "evidence": [
                                {
                                    "url": "https://example.com/note",
                                    "date": "2026-10-08",
                                    "note": "A short neutral note about the family.",
                                }
                            ],
                            "history": [
                                {
                                    "status": "community-checking",
                                    "date": "2026-10-01",
                                    "note": "An earlier short note.",
                                    "url": "https://example.com/earlier",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def history_without_url() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "history": [
                                {
                                    "status": "retracted",
                                    "date": "2026-10-08",
                                    "note": "A short neutral note.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    message = expect_error("evidence url", bad_evidence_url)
    if message:
        failures.append(message)
    message = expect_error("status without evidence", status_without_evidence)
    if message:
        failures.append(message)
    def hostile_note() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": "https://example.com/note",
                                    "date": "2026-10-08",
                                    "note": "This paper is garbage and the authors are frauds.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def quoted_evidence_url() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": 'https://example.com/a"b',
                                    "date": "2026-10-08",
                                    "note": "A short note.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    message = expect_error("history without url", history_without_url)
    if message:
        failures.append(message)
    def curated_note(note: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": "https://example.com/note",
                                    "date": "2026-10-08",
                                    "note": note,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    hostile_notes = (
        "The authors are liars.",
        "The argument is bogus.",
        "This is a crackpot note.",
        "The text was plagiarized.",
        "The note alleges plagiarism.",
        "The draft is junk.",
        "The speaker is a quack.",
        "The speaker is a charlatan.",
        "The authors cheat.",
        "The authors cheated.",
        "The note is dishonest.",
        "The claim is a sham.",
        "The note calls it junk-science.",
        "The note calls it sham-proof.",
        "The note calls it garbage-tier.",
        "The note calls it crack-pot.",
        "The note says crack pot.",
        "The author is a fraudster.",
        "The argument is fraudulent.",
        "The note shows dishonesty.",
        "The author is plagiarizing.",
        "The draft is junky.",
    )
    for sample in hostile_notes:
        message = expect_error(f"hostile note {sample}", lambda sample=sample: curated_note(sample))
        if message:
            failures.append(message)
    for sample in (
        "garbage collection",
        "fraud-detection",
        "fake-free",
        "scheme",
        "shampoo",
        "junction",
        "cheatsheet",
        "quackery",
        "cheat-sheet",
        "plagiarism-check",
        "junkers",
        "fraud detection",
        "sham pooled",
    ):
        try:
            curated_note(f"The method uses {sample}.")
        except AtlasError as exc:
            failures.append(f"a technical compound was rejected: {sample}: {exc}")
    message = expect_error("hostile note", hostile_note)
    if message:
        failures.append(message)
    message = expect_error("quoted evidence url", quoted_evidence_url)
    if message:
        failures.append(message)
    approval_error = approval_self_test()
    if approval_error:
        failures.append(approval_error)
    try:
        ordinary_solved()
        status_with_evidence()
    except AtlasError as exc:
        failures.append(f"a valid curated note was rejected: {exc}")
    cite_error = citation_self_test()
    if cite_error:
        failures.append(cite_error)
    merge_error = merge_status_self_test()
    if merge_error:
        failures.append(merge_error)
    if not CURATED_DIR.is_dir():
        failures.append("curated directory is missing")
    return failures


def citation_self_test() -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        alpha = repo / "preprints" / "alpha-paper" / "build"
        beta = repo / "preprints" / "beta-paper" / "build"
        alpha.mkdir(parents=True)
        beta.mkdir(parents=True)
        (alpha / "b.tex").write_text("See OAI:beta-paper and OAI:alpha-paper.\n", encoding="utf-8")
        (alpha / "a.bib").write_text("OAI:beta-paper\n", encoding="utf-8")
        families = [
            {"id": "001", "manuscripts": [{"slug": "alpha-paper"}]},
            {"id": "002", "manuscripts": [{"slug": "beta-paper"}]},
        ]
        attach_citations(repo, "a" * 40, families)
        edges = families[0]["citations"]
        if len(edges) != 1 or edges[0]["to"] != "002":
            return f"citation edge was {edges}"
        if edges[0]["source"] != "preprints/alpha-paper/build/a.bib":
            return f"citation receipt was {edges[0]['source']}"
        if not edges[0]["url"].endswith("/preprints/alpha-paper/build/a.bib"):
            return f"citation url was {edges[0]['url']}"
        if families[1]["citations"] != []:
            return "a self-citation or reverse edge was kept"
    return None


def approval_self_test() -> str | None:
    note = "A short neutral note about the family."
    day = "2026-10-08"
    evidence = {"url": "https://example.com/note", "date": day, "note": note}
    community = {"status": "disputed", "evidence": [evidence], "history": []}
    curated = {"362": {"id": "362", "community": community}}
    if not approval_mismatches(curated, []):
        return "a disputed status without an allowlist entry was accepted"
    entry = {
        "id": "362",
        "status": "disputed",
        "url": "https://example.com/note",
        "date": day,
        "note": note,
        "approver": "jkbennitt",
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "status-approvals.yaml"
        path.write_text(yaml.safe_dump({"approvals": [entry]}), encoding="utf-8")
        approvals = load_status_approvals(path)
    mismatches = approval_mismatches(curated, approvals)
    if mismatches:
        return f"a matching status approval was rejected: {mismatches[0]}"
    edited_note = {
        "362": {
            "id": "362",
            "community": {
                "status": "disputed",
                "evidence": [{**evidence, "note": "A short neutral note about the family, revised."}],
                "history": [],
            },
        }
    }
    if not approval_mismatches(edited_note, approvals):
        return "an edited note still matched the allowlist"
    edited_date = {
        "362": {
            "id": "362",
            "community": {
                "status": "disputed",
                "evidence": [{**evidence, "date": "2026-10-09"}],
                "history": [],
            },
        }
    }
    if not approval_mismatches(edited_date, approvals):
        return "an edited date still matched the allowlist"
    return None


def merge_status_self_test() -> str | None:
    evidence = {
        "url": "https://example.com/note",
        "date": "2026-10-08",
        "note": "A short neutral note about the family.",
    }
    community = {"status": "independently-checked", "evidence": [evidence], "history": []}
    upstream = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "upstream": {},
        "counts": {},
        "areas": [],
        "families": [
            {
                "id": "001",
                "citations": [
                    {
                        "to": "002",
                        "via": "OAI:beta-paper",
                        "source": "preprints/alpha-paper/build/a.bib",
                        "url": "https://example.com/a.bib",
                    }
                ],
            },
            {"id": "002"},
        ],
    }
    curated = {
        "001": {
            "id": "001",
            "lenses": [],
            "related": [{"to": "002", "kind": "shared-topic", "why": "Same topic.", "source": "Hand grouping"}],
            "community": community,
            "caution": None,
        }
    }
    merged = merge_data(upstream, curated, {})
    first, second = merged["families"]
    if first["community"] != community:
        return "merge did not keep the curated community status"
    if second["community"] is not None:
        return "merge invented a community status"
    if "citations" in first or first["cites"][0]["to"] != "002":
        return "merge did not project cites"
    if second["cited_by"][0]["from"] != "001" or second["cited_by"][0]["url"] != "https://example.com/a.bib":
        return "merge did not project cited_by"
    if first["cited_by"] != [] or second["cites"] != []:
        return "merge added an extra citation edge"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true", help="Check generated data and authored text.")
    parser.add_argument("--dist", type=Path, help="Check built HTML.")
    parser.add_argument("--self-test", action="store_true", help="Run guard fixtures.")
    parser.add_argument(
        "--verify-upstream",
        action="store_true",
        help="Sparse-fetch the commit named in upstream.json and fail if the snapshot differs.",
    )
    args = parser.parse_args()
    if not (args.source or args.dist or args.self_test or args.verify_upstream):
        args.source = True
        args.self_test = True
    failures: list[str] = []
    if args.self_test:
        failures.extend(self_test())
    if args.source:
        failures.extend(check_source())
    if args.verify_upstream:
        try:
            verify_recorded_upstream()
        except AtlasError as exc:
            failures.append(str(exc))
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip().splitlines()
            failures.append(detail[-1] if detail else "could not fetch upstream")
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
