"""Plan 2.8 weekly summary code-block counter.

Counts the number of fenced code blocks (```...```) in the
weekly summary markdown. Unbalanced fences are reported as
``unbalanced: true`` and the last opening fence is treated as
an unterminated block (not counted).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def compute(summary_path: Path) -> dict[str, Any]:
    text = ""
    if summary_path.is_file():
        text = summary_path.read_text(encoding="utf-8")
    in_block = False
    count = 0
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            if in_block:
                count += 1
            in_block = not in_block
    return {
        "schema_version": 1,
        "block_count":    count,
        "unbalanced":     in_block,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary code blocks\n"
        "\n"
        f"- block_count: {report['block_count']}\n"
        f"- unbalanced: {str(report['unbalanced']).lower()}\n"
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
        description="Count fenced code blocks in summary markdown.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--fail-on-unbalanced",
        action="store_true",
        help="Exit 1 if fences are unbalanced.",
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
    if args.fail_on_unbalanced and report["unbalanced"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
