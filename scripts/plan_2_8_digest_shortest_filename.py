"""Plan 2.8 digest shortest filename.

Reports the top-level file with the shortest basename. Ties
are broken by ascending name order. Subdirectories ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    names: list[str] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                names.append(p.name)
    if not names:
        return {
            "schema_version": 1,
            "found":          False,
        }
    shortest = names[0]
    for n in names[1:]:
        if len(n) < len(shortest):
            shortest = n
    return {
        "schema_version": 1,
        "found":          True,
        "name":           shortest,
        "length":         len(shortest),
    }


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return "# Plan 2.8 digest shortest filename\n\n_none_\n"
    return (
        "# Plan 2.8 digest shortest filename\n"
        "\n"
        f"- name: {report['name']}\n"
        f"- length: {report['length']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Top-level file with the shortest basename.",
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
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
