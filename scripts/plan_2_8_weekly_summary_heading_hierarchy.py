"""Plan 2.8 weekly summary heading hierarchy.

Reports the ATX heading count per level (H1..H6) in the
weekly summary. Fenced code blocks are excluded. Empty levels
report zero. ``deepest_level`` is the highest level number
seen (``0`` when no headings are present).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,6})\s+\S")


def compute(path: Path) -> dict[str, Any]:
    counts = {f"h{i}": 0 for i in range(1, 7)}
    if not path.exists():
        return {
            "schema_version": 1,
            "total":          0,
            "deepest_level":  0,
            "counts":         counts,
        }
    in_fence = False
    deepest = 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m is None:
            continue
        level = len(m.group(1))
        counts[f"h{level}"] += 1
        total += 1
        if level > deepest:
            deepest = level
    return {
        "schema_version": 1,
        "total":          total,
        "deepest_level":  deepest,
        "counts":         counts,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly summary heading hierarchy",
        "",
        f"- total: {report['total']}",
        f"- deepest_level: {report['deepest_level']}",
        "",
    ]
    for i in range(1, 7):
        key = f"h{i}"
        lines.append(f"- {key}: {report['counts'][key]}")
    lines.append("")
    return "\n".join(lines)

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
        description="Heading-level hierarchy for weekly summary.",
    )
    parser.add_argument("--summary", type=Path, required=True)
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
