"""Plan 2.8 digest empty files.

Lists zero-byte files in the artifact directory (sorted by
name ascending). Subdirectories are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    empties: list[str] = []
    total = 0
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file():
                continue
            total += 1
            if p.stat().st_size == 0:
                empties.append(p.name)
    return {
        "schema_version":   1,
        "file_count":       total,
        "empty_count":      len(empties),
        "empty_files":      empties,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest empty files",
        "",
        f"- file_count: {report['file_count']}",
        f"- empty_count: {report['empty_count']}",
        "",
    ]
    if not report["empty_files"]:
        lines.append("_none_")
    else:
        for name in report["empty_files"]:
            lines.append(f"- {name}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List zero-byte files in the artifact dir.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--fail-on-empty", action="store_true")
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
    if args.fail_on_empty and report["empty_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
