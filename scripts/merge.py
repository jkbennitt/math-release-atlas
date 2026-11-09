#!/usr/bin/env python3
"""Merge data/upstream.json with data/curated into data/families.json."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from alphaproof import ALPHAPROOF_JSON, SOURCES_JSON, catalogue_extras
from alphaevolve import ALPHAEVOLVE_JSON
from anthropic import ANTHROPIC_JSON
from atlaslib import (
    CAUTIONS_JSON,
    CURATED_DIR,
    FAMILIES_JSON,
    UPSTREAM_JSON,
    AtlasError,
    load_cautions,
    load_curated,
    load_upstream_pins,
    merge_data,
    pinned_overview_line_count,
    read_json,
    write_json,
)


def write_if_changed(path: Path, payload: dict[str, Any]) -> None:
    """Keep a file whose only difference would be generated_at.

    A second build of the same catalogue must leave the worktree clean.
    """
    if path.is_file():
        previous = read_json(path)
        previous_rest = {key: value for key, value in previous.items() if key != "generated_at"}
        payload_rest = {key: value for key, value in payload.items() if key != "generated_at"}
        if previous_rest == payload_rest:
            return
    write_json(path, payload)


def main() -> int:
    if not UPSTREAM_JSON.is_file():
        raise AtlasError("data/upstream.json is missing; run scripts/sync.py")
    upstream = read_json(UPSTREAM_JSON)
    alphaproof = read_json(ALPHAPROOF_JSON)
    anthropic = read_json(ANTHROPIC_JSON)
    alphaevolve = read_json(ALPHAEVOLVE_JSON)
    extras = catalogue_extras(upstream, alphaproof, anthropic, alphaevolve)
    registry = extras["sources"]
    pins = load_upstream_pins()
    merged = merge_data(
        upstream,
        load_curated(CURATED_DIR),
        load_cautions(CAUTIONS_JSON),
        extras,
        overview_line_count=pinned_overview_line_count(pins),
    )
    write_if_changed(FAMILIES_JSON, merged)
    write_if_changed(SOURCES_JSON, registry)
    print(f"wrote {FAMILIES_JSON.relative_to(FAMILIES_JSON.parents[1])}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
