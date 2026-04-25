"""Plan 2.8 digest smallest file.

Reports the smallest file (by byte size) in the artifact
directory. Only non-empty files are considered; ties break by
name (asc). Subdirectories are ignored. Empty dirs (or dirs
with only zero-byte files) report ``name: null``.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    best_name: str | None = None
    best_size: int | None = None
    file_count = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file():
                continue
            file_count += 1
            size = p.stat().st_size
            if size <= 0:
                continue
            if best_size is None or size < best_size:
                best_size = size
                best_name = p.name
    return {
        "schema_version":  1,
        "file_count":      file_count,
        "smallest_name":   best_name,
        "smallest_bytes":  best_size if best_size is not None else 0,
    }


def render_markdown(report: dict[str, Any]) -> str:
    name = report["smallest_name"] or "n/a"
    return (
        "# Plan 2.8 digest smallest file\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- smallest_name: {name}\n"
        f"- smallest_bytes: {report['smallest_bytes']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smallest non-empty file in artifact dir.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--fail-below-bytes", type=int, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(
            f"ERROR: artifact dir not found: {args.artifact_dir}",
            file=sys.stderr,
        )
        return 1

    report = build(args.artifact_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_below_bytes is not None
            and report["smallest_name"] is not None
            and report["smallest_bytes"] < args.fail_below_bytes):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
