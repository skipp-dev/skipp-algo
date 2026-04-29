"""Plan 2.8 weekly-summary heading-order validator.

Validates that ``## `` headings in ``weekly_summary.md`` appear in
the same order as ``DEFAULT_ORDER`` (which mirrors the TOC produced
by ``plan_2_8_weekly_summary_index.py``). Reports missing, extra,
and out-of-order headings. ``--fail-on-misorder`` gates CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

DEFAULT_ORDER: tuple[str, ...] = (
    "Status ledger summary",
    "Status flip alert",
    "Downtime",
    "Size budget",
    "Archive index",
    "Index diff",
)


_H2 = re.compile(r"^##\s+(.+?)\s*$")


def _extract(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _H2.match(line)
        if m is not None:
            out.append(m.group(1).strip())
    return out


def compute(text: str, *, order: tuple[str, ...]) -> dict[str, Any]:
    found = _extract(text)
    present_in_order = [h for h in order if h in found]
    observed_filter = [h for h in found if h in order]
    misordered = observed_filter != present_in_order
    missing = [h for h in order if h not in found]
    extra = [h for h in found if h not in order]
    return {
        "schema_version": 1,
        "expected":       list(order),
        "found":          found,
        "missing":        missing,
        "extra":          extra,
        "misordered":     misordered,
    }


def render_markdown(report: dict[str, Any]) -> str:
    def _fmt(items: list[str]) -> str:
        if not items:
            return "_(none)_"
        return ", ".join(f"`{h}`" for h in items)
    return (
        "# Plan 2.8 weekly summary heading order\n\n"
        f"- misordered: {str(report['misordered']).lower()}\n"
        f"- missing:    {_fmt(report['missing'])}\n"
        f"- extra:      {_fmt(report['extra'])}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate weekly_summary.md heading order.",
    )
    parser.add_argument("--input",  type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-misorder", action="store_true")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    report = compute(
        args.input.read_text(encoding="utf-8"),
        order=DEFAULT_ORDER,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_misorder and report["misordered"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
