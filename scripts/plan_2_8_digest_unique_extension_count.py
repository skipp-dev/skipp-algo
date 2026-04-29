"""Plan 2.8 digest unique extension count.

Reports the number of distinct lowercase file extensions
present among top-level artifact files. Files without an
extension contribute the sentinel ``<none>``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    total = 0
    exts: set[str] = set()
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                total += 1
                exts.add(p.suffix.lower() if p.suffix else "<none>")
    return {
        "schema_version":   1,
        "file_count":       total,
        "unique_extensions": len(exts),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest unique extension count\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- unique_extensions: {report['unique_extensions']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unique extension count.")
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
