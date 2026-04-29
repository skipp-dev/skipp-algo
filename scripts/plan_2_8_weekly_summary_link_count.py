"""Plan 2.8 weekly summary link count.

Counts Markdown inline links ``[text](url)`` in the weekly
summary outside fenced code blocks. Images ``![alt](src)``
are excluded. Reports the total and the count of distinct
URL targets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_FENCE = re.compile(r"^```")
_LINK = re.compile(r"(?<!\!)\[[^\]\n]+\]\(([^)\n]+)\)")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "link_count": 0,
            "distinct_urls": 0,
        }
    in_fence = False
    total = 0
    urls: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _LINK.findall(line):
            total += 1
            urls.add(m)
    return {
        "schema_version": 1,
        "link_count":     total,
        "distinct_urls":  len(urls),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary link count\n"
        "\n"
        f"- link_count: {report['link_count']}\n"
        f"- distinct_urls: {report['distinct_urls']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count Markdown inline links in weekly summary.",
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
