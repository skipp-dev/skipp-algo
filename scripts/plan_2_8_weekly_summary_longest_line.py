"""Plan 2.8 weekly summary longest line.

Reports the longest line length in the weekly summary along
with the 1-based line number where it appears. Fenced code
blocks are included. Empty/missing files return zeros and
``line_number`` = ``0``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "line_count":     0,
            "max_length":     0,
            "line_number":    0,
        }
    lines = path.read_text(encoding="utf-8").splitlines()
    max_len = 0
    max_idx = 0
    for i, line in enumerate(lines, start=1):
        if len(line) > max_len:
            max_len = len(line)
            max_idx = i
    return {
        "schema_version": 1,
        "line_count":     len(lines),
        "max_length":     max_len,
        "line_number":    max_idx,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary longest line\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- max_length: {report['max_length']}\n"
        f"- line_number: {report['line_number']}\n"
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
        description="Longest-line length in the weekly summary.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--fail-above-length", type=int, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.exists():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_above_length is not None
            and report["max_length"] > args.fail_above_length):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
