#!/usr/bin/env python3
"""Refresh the catalogue from both upstreams and merge curated notes.

The OpenAI catalogue and the AlphaProof Nexus tree are checked on every run.
Exit 0 when both pinned commits are unchanged. Exit 2 when data was rewritten
and the OpenAI README counts match. Exit 3 when data was rewritten but those
counts do not match. Exit 1 on a parse or fetch error. One run writes one
catalogue change; it does not open more than the workflow's single pull request.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from alphaproof import (
    ALPHAPROOF_JSON,
    ALPHAPROOF_SPARSE_PATHS,
    ALPHAPROOF_URL,
    SOURCES_JSON,
    build_alphaproof,
    catalogue_extras,
)
from atlaslib import (
    CAUTIONS_JSON,
    CURATED_DIR,
    FAMILIES_JSON,
    UPSTREAM_JSON,
    UPSTREAM_URL,
    AtlasError,
    build_upstream,
    diff_summary,
    load_cautions,
    load_curated,
    materialize_upstream,
    merge_data,
    read_json,
    require_upstream_ancestor,
    run_git,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / ".sync-pr-body.md"


def set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        if "\n" in value:
            handle.write(f"{name}<<ATLAS_EOF\n{value}\nATLAS_EOF\n")
        else:
            handle.write(f"{name}={value}\n")


def resolve_remote_sha(url: str, requested: str | None) -> str:
    line = run_git(["git", "ls-remote", url, "HEAD"], None, "could not read upstream HEAD").stdout
    parts = line.split()
    if not parts or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
        raise AtlasError(f"could not read upstream HEAD from {line!r}")
    head = parts[0]
    if requested is None:
        return head
    if re.fullmatch(r"[0-9a-f]{4,40}", requested) and head.startswith(requested):
        return head
    if re.fullmatch(r"[0-9a-f]{40}", requested):
        require_upstream_ancestor(url, requested)
        return requested
    raise AtlasError(f"{requested} is not upstream HEAD and is not a full commit sha")


def current_commit() -> str | None:
    if not UPSTREAM_JSON.is_file():
        return None
    commit = read_json(UPSTREAM_JSON).get("upstream", {}).get("commit")
    return commit if isinstance(commit, str) else None


def current_alphaproof_commit() -> str | None:
    if not ALPHAPROOF_JSON.is_file():
        return None
    commit = read_json(ALPHAPROOF_JSON).get("source", {}).get("commit")
    return commit if isinstance(commit, str) else None


def write_outputs(status: str, old: str, new: str, body: str, apn_old: str, apn_new: str) -> None:
    SUMMARY_PATH.write_text(body + "\n", encoding="utf-8")
    set_output("status", status)
    set_output("old", old)
    set_output("new", new)
    set_output("apn_old", apn_old)
    set_output("apn_new", apn_new)
    print(body)
    print(f"status={status}")


def alphaproof_summary(old_commit: str, payload: dict) -> str:
    counts = payload["counts"]
    gaps = {gap["id"]: gap for gap in payload["gaps"]}
    oeis = gaps["oeis-count"]
    attempted = gaps["erdos-attempted"]
    return "\n".join(
        [
            f"AlphaProof Nexus `{old_commit[:12]}` → `{payload['source']['commit'][:12]}`.",
            "",
            f"- Erdős Lean files: {counts['erdos']}",
            f"- OEIS Lean files: {counts['oeis_files']} (paper {oeis['paper_count']}/{oeis['paper_attempted']}; gap label: {oeis['label']}; status {oeis['status']})",
            f"- Stacks Lean files: {counts['stacks']}",
            f"- AI collaborator Lean files: {counts['ai_collaborator']}",
            f"- Attempted newline count {attempted['repo_newlines']}, non-empty lines {attempted['repo_entries']}, paper attempted {attempted['paper_attempted']} ({attempted['label']}; status {attempted['status']})",
            f"- Per-row provenance: {gaps['per-row-provenance']['status']}",
            "",
            payload["check_wording"],
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", help="OpenAI upstream commit. Defaults to origin HEAD.")
    parser.add_argument("--checkout", type=Path, help="Existing OpenAI clone already at the commit.")
    parser.add_argument("--alphaproof-sha", help="AlphaProof commit. Defaults to origin HEAD.")
    parser.add_argument("--alphaproof-checkout", type=Path, help="Existing AlphaProof clone already at the commit.")
    parser.add_argument("--repo-url", default=UPSTREAM_URL)
    parser.add_argument("--force", action="store_true", help="Rewrite data even if both commits match.")
    args = parser.parse_args()
    old_commit = current_commit() or ""
    old_apn = current_alphaproof_commit() or ""
    owned: list[tempfile.TemporaryDirectory[str]] = []
    try:
        if args.checkout:
            repo = args.checkout
            full = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            if args.sha and not full.startswith(args.sha):
                raise AtlasError(f"{repo} is at {full}, not {args.sha}")
        else:
            full = resolve_remote_sha(args.repo_url, args.sha)
        if args.alphaproof_checkout:
            apn_repo = args.alphaproof_checkout
            apn_full = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=apn_repo, text=True).strip()
            if args.alphaproof_sha and not apn_full.startswith(args.alphaproof_sha):
                raise AtlasError(f"{apn_repo} is at {apn_full}, not {args.alphaproof_sha}")
        else:
            apn_full = resolve_remote_sha(ALPHAPROOF_URL, args.alphaproof_sha)
        openai_changed = full != old_commit
        apn_changed = apn_full != old_apn
        if not openai_changed and not apn_changed and not args.force:
            # Both recorded commits still match HEAD. Upstream commit is unchanged.
            write_outputs("unchanged", old_commit, full, "Upstream commit is unchanged.", old_apn, apn_full)
            return 0
        if args.checkout:
            upstream, counts_ok = build_upstream(repo)
        elif openai_changed or args.force:
            scratch = tempfile.TemporaryDirectory(prefix="math-atlas-upstream-")
            owned.append(scratch)
            repo = Path(scratch.name) / "math"
            materialize_upstream(args.repo_url, full, repo)
            upstream, counts_ok = build_upstream(repo)
        else:
            upstream = read_json(UPSTREAM_JSON)
            counts_ok = bool(upstream["upstream"]["counts_match_readme"])
        if upstream["upstream"]["commit"] != full:
            raise AtlasError("built catalogue commit does not match the requested sha")
        if args.alphaproof_checkout:
            alphaproof_payload = build_alphaproof(apn_repo)
        elif apn_changed or args.force or not ALPHAPROOF_JSON.is_file():
            scratch = tempfile.TemporaryDirectory(prefix="math-atlas-alphaproof-")
            owned.append(scratch)
            apn_repo = Path(scratch.name) / "alphaproof"
            materialize_upstream(ALPHAPROOF_URL, apn_full, apn_repo, ALPHAPROOF_SPARSE_PATHS)
            alphaproof_payload = build_alphaproof(apn_repo)
        else:
            alphaproof_payload = read_json(ALPHAPROOF_JSON)
        if alphaproof_payload["source"]["commit"] != apn_full:
            raise AtlasError("built AlphaProof commit does not match the requested sha")
        old_payload = read_json(UPSTREAM_JSON) if UPSTREAM_JSON.is_file() else None
        curated = load_curated(CURATED_DIR)
        cautions = load_cautions(CAUTIONS_JSON)
        extras = catalogue_extras(upstream, alphaproof_payload)
        merged = merge_data(upstream, curated, cautions, extras)
        if openai_changed or args.force or old_payload is None:
            write_json(UPSTREAM_JSON, upstream)
        if apn_changed or args.force or not ALPHAPROOF_JSON.is_file():
            write_json(ALPHAPROOF_JSON, alphaproof_payload)
        write_json(FAMILIES_JSON, merged)
        write_json(SOURCES_JSON, extras["sources"])
        openai_body = diff_summary(old_payload, upstream, set(curated))
        body = openai_body + "\n\n" + alphaproof_summary(old_apn, alphaproof_payload)
        status = "changed" if counts_ok else "counts-mismatch"
        write_outputs(status, old_commit, full, body, old_apn, apn_full)
        return 2 if counts_ok else 3
    finally:
        for scratch in owned:
            scratch.cleanup()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        set_output("status", "error")
        sys.exit(1)
