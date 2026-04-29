"""Plan 2.8 weekly summary bold count.

Counts Markdown strong-emphasis (``**bold**`` and
``__bold__``) spans in the weekly summary. Fenced code
blocks (``` / ~~~) and inline-code runs (`` `...` ``) are
excluded. Empty markers like ``****`` and ``__`` do not
count.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_STAR = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_UNDER = re.compile(r"__(?=\S)(.+?)(?<=\S)__")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "star_count":     0,
            "underscore_count": 0,
            "total":          0,
        }
    in_fence = False
    stars = 0
    unders = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned = _INLINE_CODE.sub("", line)
        stars += len(_STAR.findall(cleaned))
        unders += len(_UNDER.findall(cleaned))
    return {
        "schema_version":   1,
        "star_count":       stars,
        "underscore_count": unders,
        "total":            stars + unders,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary bold count\n"
        "\n"
        f"- star_count: {report['star_count']}\n"
        f"- underscore_count: {report['underscore_count']}\n"
        f"- total: {report['total']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Markdown bold (strong) span count.",
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
