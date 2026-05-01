"""Plan 2.8 digest size histogram.

Buckets regular files in the artifact directory into size
ranges and reports count + total bytes per bucket. The
buckets are fixed-order:

- ``<1KB``      : size < 1024
- ``1-10KB``    : 1024   <= size < 10_240
- ``10-100KB``  : 10_240 <= size < 102_400
- ``100KB-1MB`` : 102_400 <= size < 1_048_576
- ``>=1MB``     : size >= 1_048_576

Subdirectories are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_BUCKETS = (
    ("<1KB",     0,           1024),
    ("1-10KB",   1024,        10_240),
    ("10-100KB", 10_240,      102_400),
    ("100KB-1MB", 102_400,    1_048_576),
    (">=1MB",    1_048_576,   None),
)


def _bucket(size: int) -> str:
    for label, lo, hi in _BUCKETS:
        if size >= lo and (hi is None or size < hi):
            return label
    return ">=1MB"  # defensive


def build(artifact_dir: Path) -> dict[str, Any]:
    out: dict[str, dict[str, int]] = {
        label: {"count": 0, "bytes": 0} for label, _, _ in _BUCKETS
    }
    if artifact_dir.is_dir():
        for path in artifact_dir.iterdir():
            if not path.is_file():
                continue
            size = path.stat().st_size
            label = _bucket(size)
            out[label]["count"] += 1
            out[label]["bytes"] += size
    entries = [
        {"label": label, "count": out[label]["count"],
         "bytes": out[label]["bytes"]}
        for label, _, _ in _BUCKETS
    ]
    return {
        "schema_version": 1,
        "file_count":     sum(e["count"] for e in entries),
        "total_bytes":    sum(e["bytes"] for e in entries),
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest size histogram",
        "",
        f"- file_count: {report['file_count']}",
        f"- total_bytes: {report['total_bytes']}",
        "",
        "| bucket | count | bytes |",
        "|---|---:|---:|",
    ]
    for e in report["entries"]:
        lines.append(f"| `{e['label']}` | {e['count']} | {e['bytes']} |")
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
        description="Size histogram of artifact directory.",
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
