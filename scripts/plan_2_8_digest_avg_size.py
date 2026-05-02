"""Plan 2.8 digest average file size.

Reports total bytes, file count, and mean bytes per file
across the top-level artifact directory. Subdirectories
ignored. Mean rounded to two decimals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    sizes: list[int] = []
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if p.is_file():
                try:
                    sizes.append(p.stat().st_size)
                except OSError:
                    continue
    if not sizes:
        return {
            "schema_version": 1,
            "file_count":     0,
            "total_bytes":    0,
            "avg_bytes":      0.0,
        }
    total = sum(sizes)
    return {
        "schema_version": 1,
        "file_count":     len(sizes),
        "total_bytes":    total,
        "avg_bytes":      round(total / len(sizes), 2),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest average size\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- total_bytes: {report['total_bytes']}\n"
        f"- avg_bytes: {report['avg_bytes']}\n"
    )

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
        description="Mean file size across top-level artifacts.",
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
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
