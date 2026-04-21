"""Plan 2.8 weekly summary code-block counter.

Counts the number of fenced code blocks (```...```) in the
weekly summary markdown. Unbalanced fences are reported as
``unbalanced: true`` and the last opening fence is treated as
an unterminated block (not counted).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(summary_path: Path) -> dict[str, Any]:
    text = ""
    if summary_path.is_file():
        text = summary_path.read_text(encoding="utf-8")
    in_block = False
    count = 0
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            if in_block:
                count += 1
            in_block = not in_block
    return {
        "schema_version": 1,
        "block_count":    count,
        "unbalanced":     in_block,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary code blocks\n"
        "\n"
        f"- block_count: {report['block_count']}\n"
        f"- unbalanced: {str(report['unbalanced']).lower()}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count fenced code blocks in summary markdown.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--fail-on-unbalanced",
        action="store_true",
        help="Exit 1 if fences are unbalanced.",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.is_file():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    if args.fail_on_unbalanced and report["unbalanced"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
