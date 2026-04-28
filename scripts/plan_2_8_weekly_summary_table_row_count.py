"""Plan 2.8 weekly summary table row count.

A table row is a line whose stripped form starts and ends with ``|`` and
contains at least one interior ``|``. Rows whose body consists entirely
of dashes/colons/pipes/whitespace (separator rows) are excluded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_SEP_CHARS = set("-:| \t")


def _is_row(line: str) -> bool:
    s = line.strip()
    if len(s) < 3 or not s.startswith("|") or not s.endswith("|"):
        return False
    return not s.count("|") < 2


def _is_separator(line: str) -> bool:
    s = line.strip()
    return _is_row(line) and all(ch in _SEP_CHARS for ch in s)


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":         1,
            "line_count":             0,
            "table_row_count":        0,
        }
    lines = path.read_text(encoding="utf-8").split("\n")
    n = sum(1 for ln in lines if _is_row(ln) and not _is_separator(ln))
    return {
        "schema_version":         1,
        "line_count":             len(lines),
        "table_row_count":        n,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary table row count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- table_row_count: {report['table_row_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Table row count.")
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
