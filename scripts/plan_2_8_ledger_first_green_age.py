"""Plan 2.8 ledger first green age.

Reports the age in hours between the first green capture and
a reference timestamp (``--now`` or ``datetime.now(UTC)``).
Returns ``None`` when no green records exist.
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


def _first_green(records: list[dict[str, Any]]) -> datetime | None:
    for rec in records:
        status = rec.get("status")
        if not isinstance(status, str) or status.strip().lower() != "green":
            continue
        ts = rec.get("captured_at")
        if not isinstance(ts, str):
            continue
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            continue
    return None


def compute(
    records: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    first = _first_green(records)
    if now is None:
        now = datetime.now(UTC)
    if first is None:
        hours: float | None = None
        ts_s: str | None = None
    else:
        hours = round((now - first).total_seconds() / 3600.0, 4)
        ts_s = first.isoformat()
    return {
        "schema_version":  1,
        "first_green_at":  ts_s,
        "age_hours":       hours,
    }


def render_markdown(report: dict[str, Any]) -> str:
    h = report["age_hours"]
    h_s = f"{h}" if h is not None else "n/a"
    t_s = report["first_green_at"] or "n/a"
    return (
        "# Plan 2.8 ledger first green age\n"
        "\n"
        f"- first_green_at: {t_s}\n"
        f"- age_hours: {h_s}\n"
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
        description="Hours since the first green ledger capture.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument(
        "--now", type=str, default=None,
        help="Override reference timestamp (ISO-8601).",
    )
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
            and report["age_hours"] is not None
            and report["age_hours"] < args.fail_below_hours):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
