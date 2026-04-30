"""Plan 2.8 digest missing key report.

Flags the top-level digest directory for missing required
report files. Returns presence list for a canonical set of
filenames.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

REQUIRED_FILES = (
    "weekly_summary.md",
    "state_ledger.jsonl",
)


def build(root: Path) -> dict[str, Any]:
    present: list[str] = []
    missing: list[str] = []
    exists = root.exists()
    for name in REQUIRED_FILES:
        if exists and (root / name).is_file():
            present.append(name)
        else:
            missing.append(name)
    return {
        "schema_version":    1,
        "required_count":    len(REQUIRED_FILES),
        "present_count":     len(present),
        "missing_count":     len(missing),
        "missing_files":     missing,
    }


def render_markdown(report: dict[str, Any]) -> str:
    missing = ", ".join(report["missing_files"]) or "(none)"
    return (
        "# Plan 2.8 digest missing files\n"
        "\n"
        f"- required_count: {report['required_count']}\n"
        f"- present_count: {report['present_count']}\n"
        f"- missing_count: {report['missing_count']}\n"
        f"- missing: {missing}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Missing files.")
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
