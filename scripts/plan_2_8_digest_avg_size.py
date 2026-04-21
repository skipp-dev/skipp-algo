"""Plan 2.8 digest average file size.

Reports total bytes, file count, and mean bytes per file
across the top-level artifact directory. Subdirectories
ignored. Mean rounded to two decimals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    sizes: list[int] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                try:
                    sizes.append(p.stat().st_size)
                except OSError:
                    continue
    if not sizes:
        return {
            "schema_version": 1,
            "file_count":     0,
            "total_bytes":    0,
            "avg_bytes":      0.0,
        }
    total = sum(sizes)
    return {
        "schema_version": 1,
        "file_count":     len(sizes),
        "total_bytes":    total,
        "avg_bytes":      round(total / len(sizes), 2),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest average size\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- total_bytes: {report['total_bytes']}\n"
        f"- avg_bytes: {report['avg_bytes']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mean file size across top-level artifacts.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
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
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
