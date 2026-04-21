"""Plan 2.8 digest writable fraction.

Fraction of top-level regular files that are writable.
Empty folder yields 0.0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    total_files = 0
    writable = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file() or p.is_symlink():
                continue
            total_files += 1
            if os.access(p, os.W_OK):
                writable += 1
    frac = (writable / total_files) if total_files else 0.0
    return {
        "schema_version":      1,
        "file_count":          total_files,
        "writable_fraction":   round(frac, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest writable fraction\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- writable_fraction: {report['writable_fraction']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Writable fraction.")
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
