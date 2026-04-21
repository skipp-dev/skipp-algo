"""Plan 2.8 digest per-extension bytes.

Reports total bytes per file extension in the artifact
directory. Subdirectories are ignored. Files with no suffix
use the sentinel ``(none)``. Groups are sorted by bytes
descending, then extension ascending.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _ext(name: str) -> str:
    if "." not in name or name.startswith("."):
        return "(none)"
    return "." + name.rsplit(".", 1)[-1].lower()


def build(root: Path) -> dict[str, Any]:
    by_ext: dict[str, int] = {}
    total = 0
    if root.exists():
        for p in root.iterdir():
            if not p.is_file():
                continue
            total += 1
            size = p.stat().st_size
            by_ext[_ext(p.name)] = by_ext.get(_ext(p.name), 0) + size
    entries = [
        {"extension": ext, "bytes": by_ext[ext]}
        for ext in sorted(
            by_ext.keys(),
            key=lambda k: (-by_ext[k], k),
        )
    ]
    return {
        "schema_version": 1,
        "file_count":     total,
        "group_count":    len(entries),
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest per-extension bytes",
        "",
        f"- file_count: {report['file_count']}",
        f"- group_count: {report['group_count']}",
        "",
    ]
    if not report["entries"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["entries"]:
            lines.append(f"  - {e['extension']}: {e['bytes']}B")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Total bytes per file extension.",
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
