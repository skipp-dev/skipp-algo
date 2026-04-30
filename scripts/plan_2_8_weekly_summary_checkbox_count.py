"""Plan 2.8 weekly summary checkbox count.

Counts task-list checkboxes (``- [ ]`` / ``- [x]``) lines.
Missing or empty file yields 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":   1,
            "line_count":       0,
            "checkbox_count":   0,
        }
    lines = path.read_text(encoding="utf-8").splitlines()
    count = sum(1 for line in lines if _CHECKBOX.match(line))
    return {
        "schema_version":   1,
        "line_count":       len(lines),
        "checkbox_count":   count,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary checkbox count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- checkbox_count: {report['checkbox_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Checkbox count.")
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
