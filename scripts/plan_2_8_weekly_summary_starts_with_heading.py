"""Plan 2.8 weekly summary starts-with-heading probe.

Reports whether the first non-empty line of the weekly
summary starts with ``# `` (ATX level-1 heading).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "starts_with_heading": False}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "":
            continue
        return {
            "schema_version":      1,
            "starts_with_heading": line.startswith("# "),
        }
    return {"schema_version": 1, "starts_with_heading": False}


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary starts with heading\n"
        "\n"
        f"- starts_with_heading: {report['starts_with_heading']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Starts-with-heading.")
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
