"""Plan 2.8 weekly summary footnote count.

Counts Markdown footnote references and definitions in the
weekly summary. Content inside fenced code blocks
(``` and ~~~) is excluded. References are ``[^id]``
occurrences that are not at the start of a line. Definitions
are lines that start with ``[^id]:``.
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
_DEFINITION = re.compile(r"^\s*\[\^[^\]\s]+\]:")
_REFERENCE = re.compile(r"\[\^[^\]\s]+\]")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":   1,
            "definition_count": 0,
            "reference_count":  0,
            "total":            0,
        }
    in_fence = False
    definitions = 0
    references = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.lstrip()
        if _DEFINITION.match(stripped):
            definitions += 1
            continue
        references += len(_REFERENCE.findall(line))
    return {
        "schema_version":   1,
        "definition_count": definitions,
        "reference_count":  references,
        "total":            definitions + references,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary footnote count\n"
        "\n"
        f"- definition_count: {report['definition_count']}\n"
        f"- reference_count: {report['reference_count']}\n"
        f"- total: {report['total']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Markdown footnote reference/definition count.",
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
