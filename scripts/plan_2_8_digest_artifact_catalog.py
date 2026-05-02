"""Plan 2.8 digest artifact catalog.

Walks the digest artifact directory and emits a human-friendly
catalog of known artifacts: path, size (bytes), and a short
description drawn from ``CATALOG``. Unknown files are listed under
an ``unknown`` section so operators can spot stray outputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

CATALOG: dict[str, str] = {
    "status_ledger.jsonl":
        "Append-only status ledger (JSONL).",
    "status_ledger_summary.md":
        "Aggregate summary of the ledger.",
    "status_flip_alert.md":
        "Status-flip alert report.",
    "downtime.md":
        "Non-green downtime totals.",
    "uptime.md":
        "Rolling green-uptime % over last N weeks.",
    "trend.md":
        "Per-week green % trend (markdown table).",
    "trend.json":
        "Per-week green % trend (JSON).",
    "metadata.json":
        "Generator-side metadata (python, platform, scripts).",
    "metadata_diff.md":
        "Diff vs prior metadata snapshot.",
    "latest_status.json":
        "Latest valid ledger status record.",
    "size_budget.md":
        "Digest size-budget result.",
    "archive_index.md":
        "Digest archive index.",
    "index_diff.md":
        "Weekly artifact-index diff vs prior run.",
    "weekly_summary.md":
        "Aggregated weekly summary.",
    "weekly_summary_linkcheck.md":
        "Weekly-summary anchor link check.",
    "checksums.json":
        "Artifact checksum manifest (JSON).",
    "checksums.md":
        "Artifact checksum manifest (markdown).",
    "index.md":
        "Weekly artifact index (markdown).",
    "index.json":
        "Weekly artifact index (JSON).",
    "run_stamp.json":
        "Workflow run stamp.",
    "flap_rate.md":
        "Status-flip rate per ISO week.",
}


def scan(artifact_dir: Path) -> dict[str, Any]:
    known: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    if not artifact_dir.is_dir():
        return {
            "schema_version": 1,
            "known":   [],
            "unknown": [],
            "counts":  {"known": 0, "unknown": 0, "total": 0},
        }
    for path in sorted(artifact_dir.iterdir()):
        if not path.is_file():
            continue
        entry = {
            "name": path.name,
            "size": path.stat().st_size,
        }
        if path.name in CATALOG:
            entry["description"] = CATALOG[path.name]
            known.append(entry)
        else:
            unknown.append(entry)
    return {
        "schema_version": 1,
        "known":   known,
        "unknown": unknown,
        "counts":  {
            "known":   len(known),
            "unknown": len(unknown),
            "total":   len(known) + len(unknown),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 digest artifact catalog",
        "",
        f"- total:   {c['total']}",
        f"- known:   {c['known']}",
        f"- unknown: {c['unknown']}",
        "",
        "## Known",
        "",
        "| file | size | description |",
        "|---|---:|---|",
    ]
    for e in report["known"]:
        lines.append(
            f"| `{e['name']}` | {e['size']} | {e['description']} |"
        )
    if not report["known"]:
        lines.append("| _none_ | 0 | - |")
    lines.append("")
    if report["unknown"]:
        lines.append("## Unknown")
        lines.append("")
        lines.append("| file | size |")
        lines.append("|---|---:|")
        for e in report["unknown"]:
            lines.append(f"| `{e['name']}` | {e['size']} |")
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
        description="Catalog Plan 2.8 digest artifacts.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-unknown", action="store_true")
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
    if args.fail_on_unknown and report["counts"]["unknown"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
