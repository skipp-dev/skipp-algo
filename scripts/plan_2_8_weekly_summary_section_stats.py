"""Plan 2.8 weekly-summary section statistics.

Parses a ``weekly_summary.md`` file and reports per-section
(``## ``-level headings) line and word counts. Used to flag
sections that silently went empty after a workflow change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_H2 = re.compile(r"^##\s+(.+?)\s*$")


def compute(text: str) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        m = _H2.match(line)
        if m is not None:
            if current is not None:
                sections.append(current)
            current = {
                "heading": m.group(1).strip(),
                "lines":   0,
                "words":   0,
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        current["lines"] += 1
        current["words"] += len(stripped.split())
    if current is not None:
        sections.append(current)
    empty = [s["heading"] for s in sections if s["words"] == 0]
    return {
        "schema_version": 1,
        "section_count":  len(sections),
        "empty_sections": empty,
        "sections":       sections,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekly summary - section stats",
        "",
        f"- sections: {report['section_count']}",
        f"- empty:    {len(report['empty_sections'])}",
        "",
        "| heading | lines | words |",
        "|---|---:|---:|",
    ]
    if report["sections"]:
        for s in report["sections"]:
            lines.append(
                f"| {s['heading']} | {s['lines']} | {s['words']} |"
            )
    else:
        lines.append("| _no sections_ | 0 | 0 |")
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
        description="Per-section stats of weekly_summary.md.",
    )
    parser.add_argument("--input",  type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-empty", action="store_true")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    report = compute(args.input.read_text(encoding="utf-8"))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_empty and report["empty_sections"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
