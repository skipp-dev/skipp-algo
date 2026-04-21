"""Plan 2.8 digest mp3 file count."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    total = 0
    mp = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file() or p.is_symlink():
                continue
            total += 1
            if p.suffix.lower() == ".mp3":
                mp += 1
    return {
        "schema_version":   1,
        "file_count":       total,
        "mp3_file_count":   mp,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest mp3 file count\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- mp3_file_count: {report['mp3_file_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mp3 file count.")
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
