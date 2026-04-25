"""Plan 2.8 digest numeric basename count.

Counts the number of top-level artifact files whose
basename stem (filename without extension) consists
entirely of ASCII digits (0-9) and is non-empty.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _is_numeric(stem: str) -> bool:
    return bool(stem) and all("0" <= c <= "9" for c in stem)


def build(root: Path) -> dict[str, Any]:
    total = 0
    numeric = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                total += 1
                if _is_numeric(p.stem):
                    numeric += 1
    return {
        "schema_version": 1,
        "file_count":     total,
        "numeric_count":  numeric,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest numeric basename count\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- numeric_count: {report['numeric_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Numeric basename count.")
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(
            f"ERROR: artifact dir not found: {args.artifact_dir}",
            file=sys.stderr,
        )
        return 1

    report = build(args.artifact_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
