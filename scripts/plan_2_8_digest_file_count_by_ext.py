"""Plan 2.8 digest file count by extension.

Reports the number of top-level artifact files for each
lowercase extension (including the leading dot). Files
without an extension are tallied under ``<none>``. Entries
sorted by descending count, ties broken by extension.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def build(root: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                ext = p.suffix.lower() if p.suffix else "<none>"
                counts[ext] += 1
    entries = sorted(
        ({"ext": k, "count": v} for k, v in counts.items()),
        key=lambda e: (-int(e["count"]), str(e["ext"])),
    )
    return {
        "schema_version":    1,
        "file_count":        sum(counts.values()),
        "extension_count":   len(counts),
        "entries":           entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest file count by extension",
        "",
        f"- file_count: {report['file_count']}",
        f"- extension_count: {report['extension_count']}",
        "",
    ]
    if not report["entries"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["entries"]:
            lines.append(f"  - {e['ext']}: {e['count']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="File counts per extension.",
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
