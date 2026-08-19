"""C13 status markers — the missing consumer (#4848 Review-Punkt #4).

Every C13 launchd driver writes a per-day status marker
(``cache/live/.<agent>_status_<DATE>``, content ``KIND:message:ISO-TS``), and
until 2026-08-19 exactly ONE of those ten markers had a reader (the reconcile
consumes the EOD-flatten marker, #4858). Everything else — the reconcile's own
marker included — was write-only: the 2026-08-18 reconcile ended
``DEGRADED:portfolio-after-failed`` (TWS down at 23:05 local, connection
refused on 7497) and nothing anywhere could have noticed.

This module closes the loop with two subcommands:

* ``emit`` — runs on the workstation (wired into ``run-c13-audit-push.sh``):
  collects the markers of a date window into one sanitized JSON summary
  (absolute paths reduced to basenames — raw snapshots and local paths stay
  on C13 per the data-branch privacy note) that rides the existing
  ``data/phase-a-audit`` push.
* ``check`` — runs in ``c13-daily-cron`` after the data-branch overlay:
  exits 1 if any marker of the processed trade date or the day before is not
  green. Green means ``ok``/``success`` (case-insensitive; the drivers use
  two casing conventions) — every other kind, unknown ones included, alarms
  via the cron's existing rc -> issue-opener gate. A DEGRADED cron can now be
  silent for at most one day, not "tagelang".

Both sides take their dates as explicit arguments — no clock is read here,
the drivers and the workflow own the calendar.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_json

_MARKER_NAME_RE = re.compile(r"^\.(?P<agent>[a-z0-9_]+)_status_(?P<date>\d{4}-\d{2}-\d{2})$")
_TRAILING_TS_RE = re.compile(r":(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*$")
# Any absolute-path token collapses to its basename before the summary leaves
# the workstation.
_ABS_PATH_RE = re.compile(r"/(?:[^/:\s]+/)+(?P<base>[^/:\s]+)")

GREEN_KINDS = frozenset({"ok", "success"})
SUMMARY_SCHEMA_VERSION = 1


def _parse_marker_line(line: str) -> tuple[str, str, str]:
    """Split ``KIND:message:ISO-TS`` (message may itself contain colons)."""
    body = line.strip()
    ts = ""
    ts_match = _TRAILING_TS_RE.search(body)
    if ts_match:
        ts = ts_match.group("ts")
        body = body[: ts_match.start()]
    kind, _, message = body.partition(":")
    return kind.strip(), message.strip(), ts


def _sanitize(message: str) -> str:
    return _ABS_PATH_RE.sub(lambda m: m.group("base"), message)


def _iso(day: date_type) -> str:
    return day.isoformat()


def collect_markers(live_dir: Path, *, date: str, days_back: int) -> list[dict[str, str]]:
    """Markers for ``[date - days_back + 1, date]``, sorted (date, agent)."""
    end = date_type.fromisoformat(date)
    window = {_iso(end - timedelta(days=offset)) for offset in range(days_back)}
    rows: list[dict[str, str]] = []
    for path in sorted(live_dir.iterdir()) if live_dir.is_dir() else []:
        match = _MARKER_NAME_RE.match(path.name)
        if not match or match.group("date") not in window:
            continue
        kind, message, ts = _parse_marker_line(path.read_text(encoding="utf-8", errors="replace"))
        rows.append(
            {
                "agent": match.group("agent"),
                "date": match.group("date"),
                "kind": kind,
                "message": _sanitize(message),
                "ts": ts,
            }
        )
    rows.sort(key=lambda r: (r["date"], r["agent"]))
    return rows


def emit(live_dir: Path, *, date: str, days_back: int, output: Path) -> dict[str, object]:
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "window_end": date,
        "window_days": days_back,
        "markers": collect_markers(live_dir, date=date, days_back=days_back),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(summary, output, sort_keys=True)
    return summary


def check(summary_path: Path, *, date: str) -> int:
    """Return 1 if any marker of ``date`` or the day before is not green."""
    if not summary_path.is_file():
        # A missing summary means the audit push never ran — that day is
        # already covered by the cron's own no-audit soft-skip (rc=78) and
        # the freshness monitors; a second alarm here would double-report.
        print(f"::warning::c13 status markers: no summary at {summary_path}; nothing to check")
        return 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    end = date_type.fromisoformat(date)
    scope = {_iso(end), _iso(end - timedelta(days=1))}
    in_scope = [m for m in summary.get("markers", []) if m.get("date") in scope]
    if not in_scope:
        print(f"::warning::c13 status markers: none dated {sorted(scope)} (weekend/holiday?)")
        return 0
    offenders = [m for m in in_scope if str(m.get("kind", "")).lower() not in GREEN_KINDS]
    for m in in_scope:
        print(f"marker {m['date']} {m['agent']}: {m['kind']} {m.get('message', '')}".rstrip())
    if offenders:
        names = ", ".join(f"{m['agent']}({m['date']}): {m['kind']}" for m in offenders)
        print(f"::error::c13 status markers not green: {names}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    emit_p = sub.add_parser("emit", help="collect markers into a sanitized summary JSON")
    emit_p.add_argument("--live-dir", type=Path, default=Path("cache/live"))
    emit_p.add_argument("--date", required=True, help="window end, ISO date (YYYY-MM-DD)")
    emit_p.add_argument("--days-back", type=int, default=3)
    emit_p.add_argument("--output", type=Path, required=True)

    check_p = sub.add_parser("check", help="exit 1 unless every in-scope marker is green")
    check_p.add_argument("--summary", type=Path, required=True)
    check_p.add_argument("--date", required=True, help="processed trade date (YYYY-MM-DD)")

    args = parser.parse_args(argv)
    for value in (getattr(args, "date", None),):
        if value and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            parser.error("--date must be an ISO date (YYYY-MM-DD)")

    if args.command == "emit":
        summary = emit(
            args.live_dir, date=args.date, days_back=args.days_back, output=args.output
        )
        print(json.dumps({"emitted": len(summary["markers"]), "output": str(args.output)}))
        return 0
    return check(args.summary, date=args.date)


if __name__ == "__main__":
    raise SystemExit(main())
