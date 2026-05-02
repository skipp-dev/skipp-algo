"""Plan 2.8 weekly summary table count.

Counts Markdown pipe-tables in the weekly summary outside
fenced code blocks. A table is detected by a header row
(``| a | b |``) followed by a separator row with dashes
(``| --- | --- |``). Pipes inside fenced code blocks do not
count.
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
_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _is_header(line: str) -> bool:
    s = line.strip()
    if "|" not in s:
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return any(c for c in cells) and len(cells) >= 2


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "table_count": 0}
    in_fence = False
    prev: str | None = None
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            prev = None
            continue
        if in_fence:
            prev = None
            continue
        if prev is not None and _SEP.match(line) and _is_header(prev):
            count += 1
            prev = None
            continue
        prev = line
    return {"schema_version": 1, "table_count": count}


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary table count\n"
        "\n"
        f"- table_count: {report['table_count']}\n"
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
        description="Count Markdown pipe-tables in weekly summary.",
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
