"""Append fired Plan 2.8 drift alerts to a long-running JSONL log.

Each run the weekly digest can feed its ``alerts.json`` (produced by
``plan_2_8_trend_digest.py`` via ``--alerts-file`` or the resolved
snoozed payload) into this helper. We append one JSONL record per
alert, timestamped, de-duplicated on ``(captured_at, tf, family)`` so
replays don't inflate the log.

Used for long-horizon retrospectives: "which slices have been noisy
the most weeks running?" Pure stdlib.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _now(ts: str | None) -> str:
    if ts:
        return ts
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_alerts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"alerts file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Accept either a plain list, or a digest-shaped dict with 'alerts'.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        alerts = data.get("alerts")
        if isinstance(alerts, list):
            return alerts
    return []


def _existing_keys(log: Path) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    if not log.exists():
        return keys
    for raw in log.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        key = (rec.get("captured_at") or "", rec.get("tf") or "",
               rec.get("family") or "")
        if any(key):
            keys.add(key)
    return keys


def append_alerts(
    log: Path,
    alerts: list[dict[str, Any]],
    *,
    captured_at: str,
    run_url: str | None = None,
) -> dict[str, Any]:
    seen = _existing_keys(log)
    new_records: list[dict[str, Any]] = []
    for a in alerts:
        tf = str(a.get("tf") or "")
        fam = str(a.get("family") or "")
        if not tf or not fam:
            continue
        key = (captured_at, tf, fam)
        if key in seen:
            continue
        rec = {
            "captured_at": captured_at,
            "tf": tf,
            "family": fam,
            "delta_pp": a.get("delta_pp"),
            "hr_prev": a.get("hr_prev"),
            "hr_latest": a.get("hr_latest"),
        }
        if run_url:
            rec["run_url"] = run_url
        new_records.append(rec)
        seen.add(key)
    if not new_records:
        return {"appended": 0, "skipped_duplicates": len(alerts)}

    log.parent.mkdir(parents=True, exist_ok=True)
    # Atomic append: rewrite-through-tempfile to survive partial writes.
    existing = log.read_text(encoding="utf-8") if log.exists() else ""
    fd, tmp = tempfile.mkstemp(
        dir=log.parent, prefix=".alert_history.", suffix=".jsonl",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if existing:
                fh.write(existing)
                if not existing.endswith("\n"):
                    fh.write("\n")
            for r in new_records:
                fh.write(json.dumps(r) + "\n")
        os.replace(tmp, log)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return {
        "appended": len(new_records),
        "skipped_duplicates": len(alerts) - len(new_records),
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
        description="Append fired Plan 2.8 drift alerts to a JSONL log.",
    )
    parser.add_argument("--alerts", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--captured-at", default=None,
                        help="ISO UTC timestamp; defaults to now.")
    parser.add_argument("--run-url", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        alerts = _load_alerts(args.alerts)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = append_alerts(
        args.log, alerts,
        captured_at=_now(args.captured_at),
        run_url=args.run_url,
    )
    if not args.quiet:
        print(json.dumps(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
