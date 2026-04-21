"""Plan 2.8 digest total line count.

Sum of line counts across top-level regular text-readable
files. Files that fail to decode as UTF-8 are skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    total_files = 0
    total_lines = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file() or p.is_symlink():
                continue
            total_files += 1
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            total_lines += len(text.splitlines())
    return {
        "schema_version":    1,
        "file_count":        total_files,
        "total_line_count":  total_lines,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest total line count\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- total_line_count: {report['total_line_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Total line count.")
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
