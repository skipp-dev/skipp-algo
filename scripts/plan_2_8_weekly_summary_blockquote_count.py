"""Plan 2.8 weekly summary blockquote count.

Counts lines that open a blockquote (``>`` after optional
leading whitespace) in the weekly summary, excluding fenced
code blocks. Reports both the number of blockquote lines and
the number of distinct blockquote blocks (contiguous runs of
blockquote lines).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_FENCE = re.compile(r"^```")
_BQ = re.compile(r"^\s*>")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":   1,
            "blockquote_lines": 0,
            "blockquote_blocks": 0,
        }
    in_fence = False
    lines = 0
    blocks = 0
    in_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            in_block = False
            continue
        if in_fence:
            continue
        if _BQ.match(line):
            lines += 1
            if not in_block:
                blocks += 1
                in_block = True
        else:
            in_block = False
    return {
        "schema_version":    1,
        "blockquote_lines":  lines,
        "blockquote_blocks": blocks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary blockquote count\n"
        "\n"
        f"- blockquote_lines: {report['blockquote_lines']}\n"
        f"- blockquote_blocks: {report['blockquote_blocks']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count blockquotes in weekly summary.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.exists():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
