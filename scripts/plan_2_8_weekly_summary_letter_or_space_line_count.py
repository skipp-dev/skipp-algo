"""Plan 2.8 weekly summary letter-or-space line count.

Counts non-empty lines whose every character is either an ASCII letter
(A-Z, a-z) or an ASCII space (0x20).
"""

from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path
from typing import Any


_ALLOWED = set(string.ascii_letters) | {" "}


def compute(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    cnt = sum(1 for ln in lines if ln and all(c in _ALLOWED for c in ln))
    return {
        "schema_version":               1,
        "line_count":                   len(lines),
        "letter_or_space_line_count":   cnt,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary letter or space line count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        "- letter_or_space_line_count: "
        f"{report['letter_or_space_line_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Letter-or-space line count.",
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
