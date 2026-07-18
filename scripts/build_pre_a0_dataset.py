#!/usr/bin/env python3
"""Build an atomic PRE-A0 Parquet partition from JSON input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_prep.pre_a0_schema import PreA0SnapshotRow, write_snapshot_partition


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON array of versioned snapshot rows")
    parser.add_argument("output", type=Path)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--code-revision", required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("input must be a JSON array")
    rows = [PreA0SnapshotRow(**row) for row in payload]
    manifest = write_snapshot_partition(
        rows, args.output, build_id=args.build_id, code_revision=args.code_revision
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
