"""Plan 2.8 history JSONL -> CSV exporter.

Reads ``plan_2_8_history.jsonl`` and emits a CSV with a stable
column order: ``captured_at``, ``scoring_root``, ``tf``, ``family``,
``events``, ``hit_rate_pct``, ``delta_pp``. Additional keys present
in a record are dropped; missing keys are rendered as empty cells.

Supports an optional ``--lookback-days`` window and an optional
``--fields`` override for custom column lists.

Pure stdlib; uses ``csv``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_FIELDS: tuple[str, ...] = (
    "captured_at",
    "scoring_root",
    "tf",
    "family",
    "events",
    "hit_rate_pct",
    "delta_pp",
)


def _parse_ts(s: Any) -> _dt.datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_records(log: Path) -> Iterable[dict[str, Any]]:
    for raw in log.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def filter_records(
    records: Iterable[dict[str, Any]],
    *,
    lookback_days: int | None = None,
    now: _dt.datetime | None = None,
) -> list[dict[str, Any]]:
    if lookback_days is None:
        return list(records)
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    floor = now_ - _dt.timedelta(days=lookback_days)
    out: list[dict[str, Any]] = []
    for r in records:
        ts = _parse_ts(r.get("captured_at"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.UTC)
        if ts >= floor:
            out.append(r)
    return out


def export_csv(
    records: Iterable[dict[str, Any]],
    fields: list[str],
    out_path: Path,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = {k: rec.get(k, "") for k in fields}
            writer.writerow(row)
            count += 1
    return {
        "schema_version": 1,
        "rows":           count,
        "fields":         list(fields),
        "output":         str(out_path),
    }

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
        description="Export a Plan 2.8 history JSONL to CSV.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument(
        "--fields",
        help="Comma-separated list of column names. "
             "Defaults to the stable 7-column schema.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.history.exists():
        print(f"ERROR: history not found: {args.history}", file=sys.stderr)
        return 1
    fields = [f.strip() for f in args.fields.split(",") if f.strip()] \
        if args.fields else list(DEFAULT_FIELDS)
    if not fields:
        print("ERROR: --fields cannot be empty.", file=sys.stderr)
        return 1

    records = filter_records(
        list(_iter_records(args.history)),
        lookback_days=args.lookback_days,
    )
    report = export_csv(records, fields, args.output)
    if not args.quiet:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
