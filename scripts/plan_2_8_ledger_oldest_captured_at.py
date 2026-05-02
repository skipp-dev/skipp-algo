"""Plan 2.8 ledger oldest captured_at.

Reports the earliest ``captured_at`` timestamp seen in the
ledger (valid JSON only) and its age in hours relative to a
reference timestamp. Useful for bounding ledger lifetime.
Returns ``{"found": false}`` when no usable timestamp exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _iter_records(ledger: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def compute(
    records: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    if now is None:
        now = datetime.now(UTC)
    for rec in records:
        ts = rec.get("captured_at")
        if not isinstance(ts, str):
            continue
        try:
            parsed = datetime.fromisoformat(ts)
        except ValueError:
            continue
        age_h = round((now - parsed).total_seconds() / 3600.0, 4)
        return {
            "schema_version":  1,
            "found":           True,
            "captured_at":     ts,
            "age_hours":       age_h,
        }
    return {"schema_version": 1, "found": False}


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return (
            "# Plan 2.8 ledger oldest captured_at\n"
            "\n"
            "- _none_\n"
        )
    return (
        "# Plan 2.8 ledger oldest captured_at\n"
        "\n"
        f"- captured_at: {report['captured_at']}\n"
        f"- age_hours: {report['age_hours']}\n"
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
        description="Earliest ledger captured_at and its age.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--now", type=str, default=None)
    parser.add_argument("--fail-below-hours", type=float, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    now: datetime | None = None
    if args.now is not None:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print(f"ERROR: bad --now: {args.now}", file=sys.stderr)
            return 1

    report = compute(_iter_records(args.ledger), now=now)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_below_hours is not None
            and report.get("found")
            and report["age_hours"] < args.fail_below_hours):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
