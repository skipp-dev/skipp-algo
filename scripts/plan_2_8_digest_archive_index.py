"""Plan 2.8 digest-archive index.

Scans a directory that contains prior weekly digest snapshots
(one sub-directory per run) and reports, for each sub-directory,
the file count and total size. Useful for reviewing retention.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text
import contextlib


def scan(archive_dir: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if archive_dir.exists():
        for child in sorted(archive_dir.iterdir()):
            if not child.is_dir():
                continue
            file_count = 0
            total_size = 0
            for f in child.rglob("*"):
                if not f.is_file():
                    continue
                file_count += 1
                with contextlib.suppress(OSError):
                    total_size += f.stat().st_size
            entries.append({
                "name":       child.name,
                "files":      file_count,
                "total_size": total_size,
            })
    return {
        "schema_version": 1,
        "archive_dir":    str(archive_dir),
        "counts": {
            "snapshots": len(entries),
            "total_size": sum(e["total_size"] for e in entries),
        },
        "entries": entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 digest archive index",
        "",
        f"- snapshots:  {c['snapshots']}",
        f"- total size: {c['total_size']} bytes",
        "",
    ]
    if not report["entries"]:
        lines.append("_No archive snapshots present._")
        return "\n".join(lines) + "\n"
    lines.append("| snapshot | files | size (bytes) |")
    lines.append("| --- | --- | --- |")
    for row in report["entries"]:
        lines.append(
            f"| `{row['name']}` | {row['files']} | {row['total_size']} |",
        )
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
        description="Index the Plan 2.8 digest-archive directory.",
    )
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-empty", action="store_true")
    args = parser.parse_args(argv)

    report = scan(args.archive_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_empty and report["counts"]["snapshots"] == 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
