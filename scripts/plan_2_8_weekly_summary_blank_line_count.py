"""Plan 2.8 weekly summary blank-line count.

Counts blank lines (lines consisting only of whitespace or
empty) in the weekly summary. Fenced code blocks and inline
code are NOT excluded: a blank line is a blank line
regardless of surrounding context.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "count": 0}
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            count += 1
    return {"schema_version": 1, "count": count}


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary blank-line count\n"
        "\n"
        f"- count: {report['count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Number of blank lines in the weekly summary.",
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
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
