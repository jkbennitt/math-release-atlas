#!/usr/bin/env python3
"""Refresh data/upstream.json from github.com/openai/math and merge curated notes.

Exit 0 when the pinned commit is unchanged. Exit 2 when data was rewritten and
the upstream README counts match. Exit 3 when data was rewritten but those
counts do not match. Exit 1 on a parse or fetch error.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from atlaslib import (
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
    write_json,
    CAUTIONS_JSON,
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
    line = subprocess.check_output(["git", "ls-remote", url, "HEAD"], text=True)
    parts = line.split()
    if not parts or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
        raise AtlasError(f"could not read upstream HEAD from {line!r}")
    head = parts[0]
    if requested is None:
        return head
    if re.fullmatch(r"[0-9a-f]{4,40}", requested) and head.startswith(requested):
        return head
    if re.fullmatch(r"[0-9a-f]{40}", requested):
        return requested
    raise AtlasError(f"{requested} is not upstream HEAD and is not a full commit sha")


def current_commit() -> str | None:
    if not UPSTREAM_JSON.is_file():
        return None
    commit = read_json(UPSTREAM_JSON).get("upstream", {}).get("commit")
    return commit if isinstance(commit, str) else None


def write_outputs(status: str, old: str, new: str, body: str) -> None:
    SUMMARY_PATH.write_text(body + "\n", encoding="utf-8")
    set_output("status", status)
    set_output("old", old)
    set_output("new", new)
    print(body)
    print(f"status={status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", help="Upstream commit. Defaults to origin HEAD.")
    parser.add_argument("--checkout", type=Path, help="Existing clone already at the commit.")
    parser.add_argument("--repo-url", default=UPSTREAM_URL)
    parser.add_argument("--force", action="store_true", help="Rewrite data even if the commit matches.")
    args = parser.parse_args()
    old_commit = current_commit() or ""
    owned = None
    try:
        if args.checkout:
            repo = args.checkout
            full = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            if args.sha and not full.startswith(args.sha):
                raise AtlasError(f"{repo} is at {full}, not {args.sha}")
        else:
            full = resolve_remote_sha(args.repo_url, args.sha)
            if full == old_commit and not args.force:
                write_outputs("unchanged", old_commit, full, "Upstream commit is unchanged.")
                return 0
            owned = tempfile.TemporaryDirectory(prefix="math-atlas-upstream-")
            repo = Path(owned.name) / "math"
            materialize_upstream(args.repo_url, full, repo)
        upstream, counts_ok = build_upstream(repo)
        if upstream["upstream"]["commit"] != full:
            raise AtlasError("built catalogue commit does not match the requested sha")
        old_payload = read_json(UPSTREAM_JSON) if UPSTREAM_JSON.is_file() else None
        curated = load_curated(CURATED_DIR)
        cautions = load_cautions(CAUTIONS_JSON)
        merged = merge_data(upstream, curated, cautions)
        write_json(UPSTREAM_JSON, upstream)
        write_json(FAMILIES_JSON, merged)
        body = diff_summary(old_payload, upstream, set(curated))
        status = "changed" if counts_ok else "counts-mismatch"
        write_outputs(status, old_commit, full, body)
        return 2 if counts_ok else 3
    finally:
        if owned is not None:
            owned.cleanup()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        set_output("status", "error")
        sys.exit(1)
