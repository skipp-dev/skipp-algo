"""Plan 2.8 digest lowercase-only filename count.

Counts the number of top-level artifact files whose
basename contains no uppercase ASCII letters.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _has_upper(name: str) -> bool:
    return any("A" <= c <= "Z" for c in name)


def build(root: Path) -> dict[str, Any]:
    total = 0
    lower = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                total += 1
                if not _has_upper(p.name):
                    lower += 1
    return {
        "schema_version":  1,
        "file_count":      total,
        "lowercase_count": lower,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest lowercase filename count\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- lowercase_count: {report['lowercase_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lowercase-only filename count.",
    )
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
