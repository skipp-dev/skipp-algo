"""Plan 2.8 weekly summary whitespace ratio.

Reports the share of bytes in the weekly summary that are
whitespace characters (space, tab, newline, carriage
return, form feed, vertical tab). Ratio rounded to four
decimals. Empty file yields 0.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_WS = frozenset({" ", "\t", "\n", "\r", "\f", "\v"})


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":    1,
            "total_chars":       0,
            "whitespace_chars":  0,
            "ratio":             0.0,
        }
    text = path.read_text(encoding="utf-8")
    total = len(text)
    ws = sum(1 for c in text if c in _WS)
    ratio = round(ws / total, 4) if total else 0.0
    return {
        "schema_version":    1,
        "total_chars":       total,
        "whitespace_chars":  ws,
        "ratio":             ratio,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary whitespace ratio\n"
        "\n"
        f"- total_chars: {report['total_chars']}\n"
        f"- whitespace_chars: {report['whitespace_chars']}\n"
        f"- ratio: {report['ratio']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Whitespace share of the weekly summary.",
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
