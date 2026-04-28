"""Plan 2.8 digest mean size.

Reports the arithmetic mean (and total count + bytes) of
regular-file sizes in the artifact directory. Subdirectories
are ignored. ``mean_bytes`` is ``0`` when there are no files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(artifact_dir: Path) -> dict[str, Any]:
    sizes: list[int] = []
    if artifact_dir.is_dir():
        for path in artifact_dir.iterdir():
            if path.is_file():
                sizes.append(path.stat().st_size)
    total = sum(sizes)
    count = len(sizes)
    mean = round(total / count, 2) if count else 0.0
    return {
        "schema_version": 1,
        "file_count":     count,
        "total_bytes":    total,
        "mean_bytes":     mean,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest mean size\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- total_bytes: {report['total_bytes']}\n"
        f"- mean_bytes: {report['mean_bytes']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mean file size across artifact directory.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
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
