"""Plan 2.8 digest basename length statistics.

Reports min / max / mean length of top-level artifact-file
basenames (including extension). Subdirectories ignored.
Mean is rounded to two decimal places. Empty directory
returns zeros.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    names: list[str] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                names.append(p.name)
    if not names:
        return {
            "schema_version": 1,
            "file_count":     0,
            "min_length":     0,
            "max_length":     0,
            "mean_length":    0.0,
        }
    lengths = [len(n) for n in names]
    mean = round(sum(lengths) / len(lengths), 2)
    return {
        "schema_version": 1,
        "file_count":     len(names),
        "min_length":     min(lengths),
        "max_length":     max(lengths),
        "mean_length":    mean,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest basename length stats\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- min_length: {report['min_length']}\n"
        f"- max_length: {report['max_length']}\n"
        f"- mean_length: {report['mean_length']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="min/max/mean of file-basename lengths.",
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
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
