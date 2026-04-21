"""Plan 2.8 weekly summary bullet line count."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":           1,
            "line_count":               0,
            "bullet_line_count":        0,
        }
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # Match lines whose first non-whitespace character is '-', '*' or '+'
    # followed by a space (standard Markdown unordered list markers).
    def _is_bullet(ln: str) -> bool:
        s = ln.lstrip()
        return len(s) >= 2 and s[0] in "-*+" and s[1] == " "

    n = sum(1 for ln in lines if _is_bullet(ln))
    return {
        "schema_version":           1,
        "line_count":               len(lines),
        "bullet_line_count":        n,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary bullet line count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- bullet_line_count: {report['bullet_line_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bullet line count.")
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
