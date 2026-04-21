"""Plan 2.8 weekly summary leading colon line count.

Counts lines whose first non-whitespace character is ``:``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":             1,
            "line_count":                 0,
            "leading_colon_count":        0,
        }
    lines = path.read_text(encoding="utf-8").split("\n")
    n = sum(1 for ln in lines if ln.lstrip().startswith(":"))
    return {
        "schema_version":             1,
        "line_count":                 len(lines),
        "leading_colon_count":        n,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary leading colon count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- leading_colon_count: {report['leading_colon_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leading colon count.")
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
