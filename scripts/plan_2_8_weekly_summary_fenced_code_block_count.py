"""Plan 2.8 weekly summary fenced code block count."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":               1,
            "line_count":                   0,
            "fenced_code_block_count":      0,
        }
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # Count pairs of ``` fences. A block = opening + closing fence.
    fence_lines = sum(
        1 for ln in lines if ln.lstrip().startswith("```")
    )
    return {
        "schema_version":               1,
        "line_count":                   len(lines),
        "fenced_code_block_count":      fence_lines // 2,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary fenced code block count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        "- fenced_code_block_count: "
        f"{report['fenced_code_block_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fenced code block count.",
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
