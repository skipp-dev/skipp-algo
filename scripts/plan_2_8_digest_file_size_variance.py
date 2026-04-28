"""Plan 2.8 digest file size variance.

Population variance of top-level regular-file byte sizes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    sizes: list[int] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file() or p.is_symlink():
                continue
            try:
                sizes.append(p.stat().st_size)
            except OSError:
                continue
    if sizes:
        mean = sum(sizes) / len(sizes)
        var = sum((s - mean) ** 2 for s in sizes) / len(sizes)
    else:
        var = 0.0
    return {
        "schema_version":           1,
        "file_count":               len(sizes),
        "file_size_variance":       round(var, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest file size variance\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- file_size_variance: {report['file_size_variance']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="File size variance.")
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
