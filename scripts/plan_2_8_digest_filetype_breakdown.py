"""Plan 2.8 artifact filetype breakdown.

Groups regular files in the artifact directory by file
extension (lowercase, leading dot, ``""`` for files without
an extension) and reports count + total bytes per group.
Subdirectories are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(artifact_dir: Path) -> dict[str, Any]:
    by_ext: dict[str, dict[str, int]] = {}
    if artifact_dir.is_dir():
        for path in artifact_dir.iterdir():
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            bucket = by_ext.setdefault(ext, {"count": 0, "bytes": 0})
            bucket["count"] += 1
            bucket["bytes"] += path.stat().st_size
    entries = [
        {"ext": ext, "count": v["count"], "bytes": v["bytes"]}
        for ext, v in sorted(by_ext.items())
    ]
    return {
        "schema_version": 1,
        "group_count":    len(entries),
        "file_count":     sum(e["count"] for e in entries),
        "total_bytes":    sum(e["bytes"] for e in entries),
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest filetype breakdown",
        "",
        f"- group_count: {report['group_count']}",
        f"- file_count: {report['file_count']}",
        f"- total_bytes: {report['total_bytes']}",
        "",
        "| ext | count | bytes |",
        "|---|---:|---:|",
    ]
    if report["entries"]:
        for e in report["entries"]:
            label = e["ext"] if e["ext"] else "(none)"
            lines.append(f"| `{label}` | {e['count']} | {e['bytes']} |")
    else:
        lines.append("| _none_ | 0 | 0 |")
    lines.append("")
    return "\n".join(lines) + "\n"

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Group artifact files by extension.",
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
