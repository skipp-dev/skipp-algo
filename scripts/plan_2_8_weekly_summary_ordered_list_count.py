"""Plan 2.8 weekly summary ordered list count.

Counts ordered list items (``1. foo``, ``12. bar`` etc.) in
the weekly summary outside fenced code blocks. Each matching
line counts once regardless of indentation. The number prefix
may use ``.`` or ``)`` as the separator.
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
_ITEM = re.compile(r"^\s*\d+[.)]\s+\S")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "ordered_item_count": 0}
    in_fence = False
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _ITEM.match(line):
            count += 1
    return {"schema_version": 1, "ordered_item_count": count}


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary ordered list count\n"
        "\n"
        f"- ordered_item_count: {report['ordered_item_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count ordered list items in weekly summary.",
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
