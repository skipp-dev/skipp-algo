"""Plan 2.8 runcard index.

Scans ``artifacts/plan_2_8_digest/`` (or any supplied artifact dir)
and emits a small ``runcard_index.json`` describing which sections
would be rendered by ``plan_2_8_weekly_runcard.py``. Useful as a CI
pre-flight asserting "the runcard will contain at least N sections"
and as a quick dashboard probe.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

# Kept in lockstep with plan_2_8_weekly_runcard.SECTION_MAP.
SECTION_MAP: tuple[tuple[str, str], ...] = (
    ("Weekly digest",            "weekly_digest.md"),
    ("Drift alerts (issue body)", "issue_body.md"),
    ("Snooze config lint",       "snooze_lint.md"),
    ("Snapshot diff",            "snapshot_diff.md"),
    ("Top movers",               "top_movers.md"),
    ("Slice coverage",           "coverage.md"),
    ("Slice stability",          "stability.md"),
    ("Alert-history summary",    "alert_history_summary.md"),
)


def index(artifact_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    present = 0
    for heading, fname in SECTION_MAP:
        p = artifact_dir / fname
        size = p.stat().st_size if p.exists() else 0
        is_present = p.exists() and size > 0
        if is_present:
            present += 1
        rows.append({
            "section":   heading,
            "filename":  fname,
            "exists":    p.exists(),
            "size":      size,
            "present":   is_present,
        })
    return {
        "schema_version": 1,
        "artifact_dir":   str(artifact_dir),
        "sections":       rows,
        "counts": {
            "total":   len(rows),
            "present": present,
            "missing": len(rows) - present,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 runcard index"]
    lines.append("")
    c = report["counts"]
    lines.append(f"_sections:_ {c['present']}/{c['total']} present")
    lines.append("")
    lines.append("| section | file | status |")
    lines.append("| --- | --- | --- |")
    for row in report["sections"]:
        status = "present" if row["present"] else "missing"
        lines.append(
            f"| {row['section']} | `{row['filename']}` | {status} |"
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
        description="Scan an artifact dir and emit a runcard-section index.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-present", type=int, default=0,
                        help="Exit 1 if fewer than N sections are present.")
    args = parser.parse_args(argv)

    if not args.artifact_dir.exists():
        print(f"ERROR: artifact dir not found: {args.artifact_dir}",
              file=sys.stderr)
        return 1
    report = index(args.artifact_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if report["counts"]["present"] < args.min_present:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
