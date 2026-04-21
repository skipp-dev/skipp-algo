"""Plan 2.8 digest word count.

Reports the total word count across top-level artifact-
directory files, plus a per-file breakdown sorted by name.
Words are whitespace-delimited tokens after UTF-8 decode
(replacing undecodable bytes). Binary content with no
whitespace still counts as at most one word. Subdirectories
are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _words(p: Path) -> int:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return len(text.split())


def build(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                entries.append({"name": p.name, "words": _words(p)})
    total = sum(e["words"] for e in entries)
    return {
        "schema_version": 1,
        "file_count":     len(entries),
        "total_words":    total,
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest word count",
        "",
        f"- file_count: {report['file_count']}",
        f"- total_words: {report['total_words']}",
        "",
    ]
    if not report["entries"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["entries"]:
            lines.append(f"  - {e['name']}: {e['words']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Total word count across artifact files.",
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
