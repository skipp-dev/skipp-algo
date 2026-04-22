"""Plan 2.8 weekly summary alphanumeric-only line count.

Counts non-empty lines whose every character is an ASCII letter or digit.
"""

from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path
from typing import Any

_ALNUM = frozenset(string.ascii_letters + string.digits)


def compute(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    alnum_only = sum(
        1 for line in lines if line and all(ch in _ALNUM for ch in line)
    )
    return {
        "schema_version":           1,
        "line_count":               len(lines),
        "alnum_only_line_count":    alnum_only,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary alnum only line count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- alnum_only_line_count: {report['alnum_only_line_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alnum-only line count.")
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
