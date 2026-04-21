"""Plan 2.8 alert-trend gate.

Reads the JSON output of ``scripts/plan_2_8_alert_trend.py`` and
decides whether the weekly rollout should warn (or fail, if
``--fail-on-breach``) based on configurable thresholds:

  - ``--max-rising``    — maximum tolerated ``rising`` count
  - ``--max-new``       — maximum tolerated ``new`` count
  - ``--max-falling``   — maximum tolerated ``falling`` count

``falling`` is treated as informational by default. The gate
short-circuits when the trend report has zero entries.

Output is a compact summary markdown (or single-line JSON). Pure
stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def evaluate(
    trend: dict[str, Any],
    *,
    max_rising: int | None = None,
    max_new: int | None = None,
    max_falling: int | None = None,
) -> dict[str, Any]:
    if not isinstance(trend, dict):
        trend = {}
    counts = trend.get("counts") or {}
    if not isinstance(counts, dict):
        counts = {}

    def _count(key: str) -> int:
        value = counts.get(key, 0)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    rising = _count("rising")
    new = _count("new")
    falling = _count("falling")
    entries = _count("entries")

    breaches: list[dict[str, Any]] = []
    if max_rising is not None and rising > max_rising:
        breaches.append({
            "kind": "rising", "limit": max_rising, "actual": rising,
        })
    if max_new is not None and new > max_new:
        breaches.append({
            "kind": "new", "limit": max_new, "actual": new,
        })
    if max_falling is not None and falling > max_falling:
        breaches.append({
            "kind": "falling", "limit": max_falling, "actual": falling,
        })

    return {
        "schema_version": 1,
        "entries":        entries,
        "rising":         rising,
        "new":            new,
        "falling":        falling,
        "breaches":       breaches,
        "breached":       bool(breaches),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 alert-trend gate",
        "",
        f"- entries:  {result['entries']}",
        f"- rising:   {result['rising']}",
        f"- new:      {result['new']}",
        f"- falling:  {result['falling']}",
        f"- breached: {str(result['breached']).lower()}",
        "",
    ]
    if not result["breaches"]:
        lines.append("_All thresholds within limits._")
    else:
        lines.append("| kind | limit | actual |")
        lines.append("| --- | --- | --- |")
        for b in result["breaches"]:
            lines.append(f"| {b['kind']} | {b['limit']} | {b['actual']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate the Plan 2.8 alert-trend report against "
                    "configurable thresholds.",
    )
    parser.add_argument("--trend", type=Path, required=True)
    parser.add_argument("--max-rising", type=int, default=None)
    parser.add_argument("--max-new", type=int, default=None)
    parser.add_argument("--max-falling", type=int, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-breach", action="store_true")
    args = parser.parse_args(argv)

    if not args.trend.exists():
        print(f"ERROR: trend not found: {args.trend}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.trend.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: trend is not valid JSON: {exc}", file=sys.stderr)
        return 1

    result = evaluate(
        payload,
        max_rising=args.max_rising,
        max_new=args.max_new,
        max_falling=args.max_falling,
    )
    body = render_markdown(result) if args.format == "md" \
        else json.dumps(result) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    if args.fail_on_breach and result["breached"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
