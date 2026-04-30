"""Plan 2.8 weekly summary reference definitions.

Counts Markdown link reference definitions of the form
``[label]: url`` in the weekly summary. Fenced code blocks
(``` / ~~~) are excluded. A definition must appear at the
start of a line (optional leading whitespace) and include a
non-empty label and a non-empty URL.
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
_DEF = re.compile(r"^\s*\[([^\]\s][^\]]*)\]:\s+\S")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "count": 0, "labels": []}
    in_fence = False
    labels: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _DEF.match(line)
        if match:
            labels.append(match.group(1).strip())
    labels.sort()
    return {
        "schema_version": 1,
        "count":          len(labels),
        "labels":         labels,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly summary reference definitions",
        "",
        f"- count: {report['count']}",
        "",
    ]
    if not report["labels"]:
        lines.extend(["_none_", ""])
    else:
        for label in report["labels"]:
            lines.append(f"  - {label}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Markdown link-reference-definition count.",
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
