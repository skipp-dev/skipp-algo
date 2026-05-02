"""Summarize a ``plan_2_8_alert_history.jsonl`` log.

Reads the alert history produced by
``scripts/plan_2_8_alert_history.py`` and ranks TF×family slices by
how frequently they fired over a configurable lookback window.
Also reports the most recent `delta_pp` per slice and the time of
the last occurrence. Read-only, stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _parse_iso(ts: str) -> _dt.datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(ts)


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"alert log not found: {path}")
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summarize(
    records: list[dict[str, Any]],
    *,
    lookback_days: int = 90,
    now: _dt.datetime | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    cutoff = now_ - _dt.timedelta(days=lookback_days)
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in records:
        try:
            ts = _parse_iso(rec["captured_at"])
        except (KeyError, ValueError):
            continue
        if ts < cutoff or ts > now_:
            continue
        key = (str(rec.get("tf", "")), str(rec.get("family", "")))
        if not all(key):
            continue
        b = buckets.setdefault(key, {
            "tf": key[0], "family": key[1], "count": 0,
            "first_seen": ts, "last_seen": ts,
            "last_delta_pp": rec.get("delta_pp"),
            "max_abs_delta_pp": abs(rec.get("delta_pp") or 0.0),
        })
        b["count"] += 1
        if ts < b["first_seen"]:
            b["first_seen"] = ts
        if ts >= b["last_seen"]:
            b["last_seen"] = ts
            b["last_delta_pp"] = rec.get("delta_pp")
        ad = abs(rec.get("delta_pp") or 0.0)
        if ad > b["max_abs_delta_pp"]:
            b["max_abs_delta_pp"] = ad
    ranked = sorted(
        buckets.values(),
        key=lambda r: (-r["count"], -r["max_abs_delta_pp"], r["tf"], r["family"]),
    )
    top = ranked[:top_n]
    # Serialize datetimes for a clean JSON payload.
    for row in top:
        row["first_seen"] = row["first_seen"].strftime("%Y-%m-%dT%H:%M:%SZ")
        row["last_seen"] = row["last_seen"].strftime("%Y-%m-%dT%H:%M:%SZ")
        row["max_abs_delta_pp"] = round(row["max_abs_delta_pp"], 6)
    return {
        "schema_version": 1,
        "status": "ok" if records else "empty",
        "lookback_days": lookback_days,
        "now": now_.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records_total": len(records),
        "records_in_window": sum(b["count"] for b in buckets.values()),
        "top": top,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 alert-history summary"]
    lines.append("")
    lines.append(f"- now:              `{report['now']}`")
    lines.append(f"- lookback:         {report['lookback_days']} days")
    lines.append(f"- records (total):  {report['records_total']}")
    lines.append(f"- records (window): {report['records_in_window']}")
    lines.append("")
    if not report["top"]:
        lines.append("No alerts in the selected window.")
        return "\n".join(lines) + "\n"
    lines.append(
        "| tf | family | count | last | last_delta_pp | max_abs_delta_pp |"
    )
    lines.append(
        "|----|--------|------:|------|-------------:|----------------:|"
    )
    for r in report["top"]:
        last_delta = "-" if r.get("last_delta_pp") is None \
            else f"{r['last_delta_pp']:+.4f}"
        lines.append(
            f"| {r['tf']} | {r['family']} | {r['count']} | "
            f"{r['last_seen']} | {last_delta} | "
            f"{r['max_abs_delta_pp']:.4f} |"
        )
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
        description="Summarize plan_2_8_alert_history.jsonl.",
    )
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--now", default=None,
                        help="ISO timestamp override (tests only).")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        recs = _read_log(args.log)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    now_ = None if args.now is None else _parse_iso(args.now)
    report = summarize(
        recs, lookback_days=args.lookback_days, now=now_, top_n=args.top_n,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
