"""Plan 2.8 digest file age stats.

Reports file-age statistics (seconds since mtime) for files in
the artifact directory. Subdirectories are ignored. Empty
directories return zeros. ``now_ts`` may be supplied to make
the report deterministic in tests; defaults to ``time.time()``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def build(root: Path, now_ts: float | None = None) -> dict[str, Any]:
    if now_ts is None:
        now_ts = time.time()
    ages: list[float] = []
    if root.exists():
        for p in root.iterdir():
            if p.is_file():
                ages.append(max(0.0, now_ts - p.stat().st_mtime))
    if not ages:
        return {
            "schema_version":  1,
            "file_count":      0,
            "min_age_seconds": 0.0,
            "mean_age_seconds": 0.0,
            "max_age_seconds": 0.0,
        }
    return {
        "schema_version":  1,
        "file_count":      len(ages),
        "min_age_seconds": round(min(ages), 2),
        "mean_age_seconds": round(sum(ages) / len(ages), 2),
        "max_age_seconds": round(max(ages), 2),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 digest file age stats\n"
        "\n"
        f"- file_count: {report['file_count']}\n"
        f"- min_age_seconds: {report['min_age_seconds']}\n"
        f"- mean_age_seconds: {report['mean_age_seconds']}\n"
        f"- max_age_seconds: {report['max_age_seconds']}\n"
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
        description="File-age statistics for the artifact dir.",
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
