"""Plan 2.8 digest file size median.

Median (statistics.median) of top-level regular-file sizes
in bytes. Empty folder yields 0.0.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    total = 0
    sizes: list[int] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            total += 1
            if not p.is_file() or p.is_symlink():
                continue
            try:
                sizes.append(p.stat().st_size)
            except OSError:
                continue
    median = float(statistics.median(sizes)) if sizes else 0.0
    return {
        "schema_version":            1,
        "entry_count":               total,
        "file_size_median_bytes":    round(median, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest file size median\n"
        "\n"
        f"- entry_count: {report['entry_count']}\n"
        f"- file_size_median_bytes: {report['file_size_median_bytes']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="File size median.")
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
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
