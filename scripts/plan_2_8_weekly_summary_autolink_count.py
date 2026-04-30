"""Plan 2.8 weekly summary autolink count.

Counts Markdown autolinks of the form ``<http://...>``,
``<https://...>``, and ``<mailto:...>`` in the weekly
summary. Fenced code blocks (``` / ~~~) and inline-code runs
(`` `...` ``) are excluded.
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
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]+)>")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "count": 0}
    in_fence = False
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned = _INLINE_CODE.sub("", line)
        total += len(_AUTOLINK.findall(cleaned))
    return {"schema_version": 1, "count": total}


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary autolink count\n"
        "\n"
        f"- count: {report['count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Markdown autolink count.",
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
