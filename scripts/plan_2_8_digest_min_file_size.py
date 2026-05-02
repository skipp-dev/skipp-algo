"""Plan 2.8 digest min file size.

Reports the smallest size in bytes across top-level
regular files (excluding symlinks). Empty folder yields 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path) -> dict[str, Any]:
    total = 0
    min_size: int | None = None
    if root.exists():
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            total += 1
            if not p.is_file() or p.is_symlink():
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if min_size is None or sz < min_size:
                min_size = sz
    return {
        "schema_version":      1,
        "entry_count":         total,
        "min_file_size_bytes": 0 if min_size is None else min_size,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest min file size\n"
        "\n"
        f"- entry_count: {report['entry_count']}\n"
        f"- min_file_size_bytes: {report['min_file_size_bytes']}\n"
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
    parser = argparse.ArgumentParser(description="Min file size.")
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
