"""Plan 2.8 worst-day identifier.

Groups ledger records by UTC calendar date and flags the date
with the most non-green records (amber+red). Ties break by
earliest date so reports are deterministic.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


def _parse_ts(raw: Any) -> _dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, int]] = {}
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        key = ts.astimezone(_dt.UTC).strftime("%Y-%m-%d")
        slot = buckets.setdefault(key, {k: 0 for k in VALID_STATUSES})
        slot[s] += 1
    if not buckets:
        return {
            "schema_version": 1,
            "worst_date":     None,
            "non_green":      0,
            "counts":         None,
        }
    ranked = sorted(
        buckets.items(),
        key=lambda kv: (-(kv[1]["amber"] + kv[1]["red"]), kv[0]),
    )
    worst_date, slot = ranked[0]
    return {
        "schema_version": 1,
        "worst_date":     worst_date,
        "non_green":      slot["amber"] + slot["red"],
        "counts":         slot,
    }


def render_markdown(report: dict[str, Any]) -> str:
    if report["worst_date"] is None:
        return (
            "# Plan 2.8 worst day\n\n"
            "_no records_\n"
        )
    c = report["counts"]
    return (
        "# Plan 2.8 worst day\n\n"
        f"- worst_date: {report['worst_date']}\n"
        f"- non_green:  {report['non_green']}\n"
        f"- counts:     green={c['green']}, amber={c['amber']},"
        f" red={c['red']}, unknown={c['unknown']}\n"
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
        description="Identify the worst (most non-green) UTC date.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter_records(args.ledger))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
