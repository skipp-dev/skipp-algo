"""Plan 2.8 trend-threshold alert.

Reads the JSON output of ``plan_2_8_ledger_trend.py`` and checks
whether the most recent week's ``green_pct`` is at or above a
configurable threshold.

Exit code ``1`` with ``--fail-below`` when the most recent week
is below the threshold (or when there are no weeks at all).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("trend file must be a JSON object")
    return data


def evaluate(trend: dict[str, Any], *,
             threshold: float) -> dict[str, Any]:
    weeks = trend.get("weeks", []) or []
    latest: dict[str, Any] | None = None
    if isinstance(weeks, list) and weeks:
        candidate = weeks[-1]
        if isinstance(candidate, dict):
            latest = candidate
    pct = 0.0
    if latest is not None:
        raw = latest.get("green_pct")
        if isinstance(raw, (int, float)):
            pct = float(raw)
    passed = latest is not None and pct >= threshold
    return {
        "schema_version": 1,
        "threshold":      threshold,
        "latest_week":    (latest or {}).get("week"),
        "latest_pct":     pct,
        "passed":         passed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    state = "PASS" if report["passed"] else "FAIL"
    return (
        "# Plan 2.8 trend-threshold alert\n\n"
        f"- latest week: {report['latest_week'] or 'n/a'}\n"
        f"- green %:     {report['latest_pct']:.2f}\n"
        f"- threshold:   {report['threshold']:.2f}\n"
        f"- result:      {state}\n"
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
        description="Alert if latest weekly green %% is below threshold.",
    )
    parser.add_argument("--trend-json", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=90.0)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-below", action="store_true")
    args = parser.parse_args(argv)

    if not args.trend_json.is_file():
        print(f"ERROR: trend JSON not found: {args.trend_json}",
              file=sys.stderr)
        return 1
    try:
        trend = load(args.trend_json)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: invalid trend JSON: {exc}", file=sys.stderr)
        return 1

    report = evaluate(trend, threshold=args.threshold)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_below and not report["passed"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
