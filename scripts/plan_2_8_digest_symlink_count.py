"""Plan 2.8 digest symlink count.

Counts the number of top-level directory entries that are
symbolic links (regardless of their target type).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    total = 0
    symlinks = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            total += 1
            if p.is_symlink():
                symlinks += 1
    return {
        "schema_version": 1,
        "entry_count":    total,
        "symlink_count":  symlinks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest symlink count\n"
        "\n"
        f"- entry_count: {report['entry_count']}\n"
        f"- symlink_count: {report['symlink_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Symlink count.")
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
