#!/usr/bin/env python3
"""Merge data/upstream.json with data/curated into data/families.json."""

from __future__ import annotations

import sys

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
    merged = merge_data(
        read_json(UPSTREAM_JSON),
        load_curated(CURATED_DIR),
        load_cautions(CAUTIONS_JSON),
    )
    write_json(FAMILIES_JSON, merged)
    print(f"wrote {FAMILIES_JSON.relative_to(FAMILIES_JSON.parents[1])}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
