"""Plan 2.8 weekly summary emphasis count.

Counts Markdown emphasis runs in the weekly summary outside
fenced code blocks:
- ``bold_count`` — ``**...**`` spans with non-empty content.
- ``italic_count`` — single ``*...*`` or ``_..._`` spans with
  non-empty content. Bold markers are stripped first so that
  ``**x**`` does not double-count as italic.
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
_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC_STAR = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?!\*)")
_ITALIC_UNDER = re.compile(r"(?<![\w_])_([^_\n]+?)_(?!\w)")


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
            "schema_version": 1,
            "bold_count":     0,
            "italic_count":   0,
        }
    text = _outside_fences(path.read_text(encoding="utf-8"))
    bold = len(_BOLD.findall(text))
    stripped = _BOLD.sub("", text)
    italic = (
        len(_ITALIC_STAR.findall(stripped))
        + len(_ITALIC_UNDER.findall(stripped))
    )
    return {
        "schema_version": 1,
        "bold_count":     bold,
        "italic_count":   italic,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary emphasis count\n"
        "\n"
        f"- bold_count: {report['bold_count']}\n"
        f"- italic_count: {report['italic_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count bold/italic runs in weekly summary.",
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
