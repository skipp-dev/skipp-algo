"""Plan 2.8 weekly summary preview.

Emits the first N lines of the given summary markdown file as
a short preview block, useful for alert channels and PR
comments where the full summary is too long.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def preview(summary_path: Path, max_lines: int) -> dict[str, Any]:
    if max_lines < 0:
        max_lines = 0
    lines: list[str] = []
    if summary_path.is_file():
        lines = summary_path.read_text(encoding="utf-8").splitlines()
    head = lines[:max_lines]
    return {
        "schema_version": 1,
        "total_lines":    len(lines),
        "preview_lines":  len(head),
        "preview":        head,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly summary preview",
        "",
        f"- total_lines: {report['total_lines']}",
        f"- preview_lines: {report['preview_lines']}",
        "",
    ]
    if report["preview"]:
        lines.append("```")
        lines.extend(report["preview"])
        lines.append("```")
    else:
        lines.append("_empty_")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview first N lines of a summary markdown file.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.is_file():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = preview(args.summary, args.max_lines)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
