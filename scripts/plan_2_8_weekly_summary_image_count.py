"""Plan 2.8 weekly summary image count.

Counts Markdown image tags (``![alt](src)``) in the weekly
summary outside fenced code blocks. Reports the total image
count and how many distinct ``src`` values appear.
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
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")


def _outside_fences(text: str) -> str:
    keep: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            keep.append(line)
    return "\n".join(keep)


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":  1,
            "image_count":     0,
            "distinct_srcs":   0,
        }
    text = _outside_fences(path.read_text(encoding="utf-8"))
    matches = _IMAGE.findall(text)
    srcs = {src.strip() for _, src in matches}
    return {
        "schema_version":  1,
        "image_count":     len(matches),
        "distinct_srcs":   len(srcs),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary image count\n"
        "\n"
        f"- image_count: {report['image_count']}\n"
        f"- distinct_srcs: {report['distinct_srcs']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count images in weekly summary.",
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
