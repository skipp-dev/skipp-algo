"""Plan 2.8 weekly summary list stats.

Counts bullet list items (lines beginning with ``- `` or
``* ``, optional leading whitespace) vs numbered list items
(lines beginning with a digit followed by ``. ``) in the
weekly summary markdown. Lines inside fenced code blocks
(``` ``` ```) are excluded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_BULLET = re.compile(r"^\s*[-*]\s+\S")
_NUMBERED = re.compile(r"^\s*\d+\.\s+\S")


def compute(summary_path: Path) -> dict[str, Any]:
    text = ""
    if summary_path.is_file():
        text = summary_path.read_text(encoding="utf-8")
    in_block = False
    bullets = 0
    numbered = 0
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            continue
        if _BULLET.match(raw):
            bullets += 1
        elif _NUMBERED.match(raw):
            numbered += 1
    return {
        "schema_version": 1,
        "bullet_count":   bullets,
        "numbered_count": numbered,
        "total":          bullets + numbered,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary list stats\n"
        "\n"
        f"- bullet_count: {report['bullet_count']}\n"
        f"- numbered_count: {report['numbered_count']}\n"
        f"- total: {report['total']}\n"
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
        description="Count list items in the weekly summary markdown.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--fail-below-total", type=int, default=None,
        help="Exit 1 if total list items are below this threshold.",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.is_file():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_below_total is not None
            and report["total"] < args.fail_below_total):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
