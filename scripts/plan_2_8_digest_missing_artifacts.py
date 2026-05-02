"""Plan 2.8 missing-artifact reporter.

Compares the filenames present in an artifact directory against
a pinned ``REQUIRED`` list and reports which are missing. This
catches workflow regressions where a step silently stopped
producing its output even though the upload step was skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

REQUIRED: tuple[str, ...] = (
    "status_ledger.jsonl",
    "weekly_summary.md",
    "downtime.md",
    "size_budget.md",
    "archive_index.md",
    "index_diff.md",
    "uptime_pct.md",
    "file_manifest.md",
    "weekly_summary_index.md",
    "latest_status.md",
    "longest_streak.md",
    "metadata.json",
    "metadata_diff.md",
    "trend.md",
    "trend.json",
    "linkcheck.md",
    "flap_rate.md",
    "trend_threshold.md",
    "artifact_catalog.md",
    "status_today.md",
    "recent_changes.md",
    "weekly_summary_toc.md",
    "streak_now.md",
    "artifact_age.md",
    "month_summary.md",
    "worst_day.md",
    "catalog_diff.md",
    "section_stats.md",
    "best_day.md",
    "size_trend.md",
    "heading_order.md",
)


def scan(artifact_dir: Path) -> dict[str, Any]:
    present: set[str] = set()
    if artifact_dir.is_dir():
        for path in artifact_dir.iterdir():
            if path.is_file():
                present.add(path.name)
    missing = sorted(n for n in REQUIRED if n not in present)
    extra = sorted(n for n in present if n not in REQUIRED)
    return {
        "schema_version": 1,
        "required":       list(REQUIRED),
        "present_count":  len(present),
        "missing":        missing,
        "extra":          extra,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 missing artifacts",
        "",
        f"- required: {len(report['required'])}",
        f"- missing:  {len(report['missing'])}",
        f"- extra:    {len(report['extra'])}",
        "",
        "### Missing",
        "",
    ]
    if report["missing"]:
        lines.extend(f"- `{n}`" for n in report["missing"])
    else:
        lines.append("_(none)_")
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
        description="Report missing required digest artifacts.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args(argv)

    if not args.artifact_dir.is_dir():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1

    report = scan(args.artifact_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_missing and report["missing"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
