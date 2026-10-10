#!/usr/bin/env python3
"""Merge data/upstream.json with data/curated into data/families.json."""

from __future__ import annotations

import sys

from alphaproof import ALPHAPROOF_JSON, SOURCES_JSON, catalogue_extras
from anthropic import ANTHROPIC_JSON
from atlaslib import (
    CAUTIONS_JSON,
    CURATED_DIR,
    FAMILIES_JSON,
    UPSTREAM_JSON,
    AtlasError,
    load_cautions,
    load_curated,
    merge_data,
    read_json,
    write_json,
)


def main() -> int:
    if not UPSTREAM_JSON.is_file():
        raise AtlasError("data/upstream.json is missing; run scripts/sync.py")
    upstream = read_json(UPSTREAM_JSON)
    alphaproof = read_json(ALPHAPROOF_JSON)
    anthropic = read_json(ANTHROPIC_JSON)
    extras = catalogue_extras(upstream, alphaproof, anthropic)
    registry = extras["sources"]
    merged = merge_data(
        upstream,
        load_curated(CURATED_DIR),
        load_cautions(CAUTIONS_JSON),
        extras,
    )
    write_json(FAMILIES_JSON, merged)
    write_json(SOURCES_JSON, registry)
    print(f"wrote {FAMILIES_JSON.relative_to(FAMILIES_JSON.parents[1])}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
