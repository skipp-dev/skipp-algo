"""Plan 2.8 digest summary-index.

Walks an artifact directory and builds a manifest of every
``.md`` file with its size and first ``# `` heading (falls back
to the filename when none is present). Complements the
file-manifest helper (which scans scripts/tests) by surfacing
the actual digest outputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _first_heading(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip()
    except (OSError, UnicodeDecodeError):
        return None
    return None


def build(artifact_dir: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if artifact_dir.is_dir():
        for path in sorted(artifact_dir.iterdir()):
            if not path.is_file() or path.suffix != ".md":
                continue
            heading = _first_heading(path)
            entries.append({
                "name":    path.name,
                "size":    path.stat().st_size,
                "heading": heading if heading else path.name,
            })
    return {
        "schema_version": 1,
        "count":          len(entries),
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest summary index",
        "",
        f"- count: {report['count']}",
        "",
        "| file | size | heading |",
        "|---|---:|---|",
    ]
    if report["entries"]:
        for e in report["entries"]:
            lines.append(
                f"| `{e['name']}` | {e['size']} | {e['heading']} |"
            )
    else:
        lines.append("| _none_ | 0 | - |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a .md manifest of an artifact directory.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
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
