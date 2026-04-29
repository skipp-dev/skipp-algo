"""Plan 2.8 digest duplicate sizes.

Groups artifact-directory files by byte size and reports
groups with two or more files sharing the same size (suspect
duplicates). Subdirectories are ignored. Groups are sorted by
size ascending; names within a group are sorted ascending.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    by_size: dict[int, list[str]] = {}
    total = 0
    if root.exists():
        for p in root.iterdir():
            if not p.is_file():
                continue
            total += 1
            size = p.stat().st_size
            by_size.setdefault(size, []).append(p.name)
    groups: list[dict[str, Any]] = []
    for size in sorted(by_size.keys()):
        names = by_size[size]
        if len(names) >= 2:
            groups.append({"size": size, "names": sorted(names)})
    return {
        "schema_version": 1,
        "file_count":     total,
        "group_count":    len(groups),
        "groups":         groups,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest duplicate sizes",
        "",
        f"- file_count: {report['file_count']}",
        f"- group_count: {report['group_count']}",
        "",
    ]
    if not report["groups"]:
        lines.extend(["_none_", ""])
    else:
        for g in report["groups"]:
            joined = ", ".join(g["names"])
            lines.append(f"  - {g['size']}B: {joined}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Groups of artifact files sharing identical sizes.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument(
        "--fail-on-duplicates", action="store_true",
        help="Exit 1 if any duplicate-size groups exist.",
    )
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
    if args.fail_on_duplicates and report["group_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
