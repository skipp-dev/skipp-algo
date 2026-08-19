"""C13 status markers — the missing consumer (#4848 Review-Punkt #4).

Every C13 launchd driver writes a per-day status marker
(``.<agent>_status_<DATE>``, content ``KIND:message:ISO-TS``) into one of the
three directories in :data:`MARKER_DIRS` — ``cache/live`` holds nine of the
twelve, the imbalance collector and the WSH feed use ``cache/imbalance`` and
``cache/wsh``. Until 2026-08-19 this module scanned ``cache/live`` alone, so
those three stayed unread despite the promise in this line (K5), and
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
  green. Green means every line's kind is ``ok``/``success``
  (case-insensitive) — every other kind, unknown ones included, alarms via
  the cron's existing rc -> issue-opener gate. A DEGRADED cron can now be
  silent for at most one day, not "tagelang".

Marker formats are the MEASURED population on C13, not an assumed convention
(all 16 real markers of 2026-08-16..18, sampled 2026-08-19 — the first cut
parsed only ``KIND:msg`` and would have alarmed on every green day):
``KIND:msg:ISO-TS``, ``KIND|msg``, ``KIND msg``, and the commercial driver's
append file with one ``HH:MM:SSZ KIND|msg`` line per fire — worst line wins.

Both sides take their dates as explicit arguments — no clock is read here,
the drivers and the workflow own the calendar.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_json

_MARKER_NAME_RE = re.compile(r"^\.(?P<agent>[a-z0-9_]+)_status_(?P<date>\d{4}-\d{2}-\d{2})$")
_TRAILING_TS_RE = re.compile(r":(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*$")
# Append-style markers (commercial_shadow) prefix each fired line with a bare
# clock time; the kind follows it.
_LINE_TS_PREFIX_RE = re.compile(r"^\d{2}:\d{2}:\d{2}Z\s+")
# The kind is the leading word, terminated by any of the three measured
# delimiters (colon, pipe, space) or end of line.
_KIND_RE = re.compile(r"^(?P<kind>[A-Za-z_]+)(?:[:| ]|$)")
# Any absolute-path token collapses to its basename before the summary leaves
# the workstation.
_ABS_PATH_RE = re.compile(r"/(?:[^/:\s]+/)+(?P<base>[^/:\s]+)")

GREEN_KINDS = frozenset({"ok", "success"})
SUMMARY_SCHEMA_VERSION = 2

# The MEASURED marker-directory population (2026-08-19, Doppelgaenger K5): the
# launchd drivers write into three directories, not one. Kept in lockstep with
# the drivers by tests/test_c13_status_markers.py, which derives the set from
# the marker paths in automation/launchd/*.sh instead of trusting this literal.
# c13-daily-cron.yml overlays exactly these three from the data branch.
MARKER_DIRS: tuple[Path, ...] = (
    Path("cache/live"),
    Path("cache/imbalance"),
    Path("cache/wsh"),
)


def _parse_marker_line(line: str) -> tuple[str, str, str]:
    """One marker line -> (kind, message, ts) across the measured formats."""
    body = line.strip()
    ts = ""
    ts_match = _TRAILING_TS_RE.search(body)
    if ts_match:
        ts = ts_match.group("ts")
        body = body[: ts_match.start()]
    body = _LINE_TS_PREFIX_RE.sub("", body)
    kind_match = _KIND_RE.match(body)
    if not kind_match:
        # Unparseable head: surface it verbatim as the kind so the alarm text
        # shows the junk — unknown kinds fail closed downstream.
        return body, "", ts
    kind = kind_match.group("kind")
    message = body[kind_match.end("kind") :].lstrip(":| ")
    return kind, message.strip(), ts


def _parse_marker_content(text: str) -> tuple[str, str, str]:
    """Whole marker file -> worst line wins (append-style markers carry one
    line per fire; any single non-green fire must alarm)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "EMPTY-MARKER", "", ""
    parsed = [_parse_marker_line(line) for line in lines]
    for kind, message, ts in parsed:
        if kind.lower() not in GREEN_KINDS:
            return kind, message, ts
    return parsed[-1]


def _sanitize(message: str) -> str:
    return _ABS_PATH_RE.sub(lambda m: m.group("base"), message)


def _iso(day: date_type) -> str:
    return day.isoformat()


def collect_markers(
    live_dir: Path | Sequence[Path], *, date: str, days_back: int
) -> list[dict[str, str]]:
    """Markers for ``[date - days_back + 1, date]``, sorted (dir, date, agent).

    Accepts one directory or several. Several is the production case: the C13
    drivers do NOT all write into ``cache/live`` — the imbalance collector uses
    ``cache/imbalance`` and the WSH feed ``cache/wsh`` (measured 2026-08-19,
    Doppelgaenger-Sweep K5). Scanning only ``cache/live`` made 3 of 12 marker
    paths invisible to this consumer while its own docstring promised "every
    driver", so a silent failure in those two chains stayed silent. The
    directory is carried into each row because two directories can hold the
    same agent name (``.push_status_`` exists in both non-live dirs).
    """
    dirs = [live_dir] if isinstance(live_dir, Path) else list(live_dir)
    end = date_type.fromisoformat(date)
    window = {_iso(end - timedelta(days=offset)) for offset in range(days_back)}
    rows: list[dict[str, str]] = []
    for directory in dirs:
        for path in sorted(directory.iterdir()) if directory.is_dir() else []:
            match = _MARKER_NAME_RE.match(path.name)
            if not match or match.group("date") not in window:
                continue
            kind, message, ts = _parse_marker_content(
                path.read_text(encoding="utf-8", errors="replace")
            )
            rows.append(
                {
                    "agent": match.group("agent"),
                    "dir": directory.as_posix(),
                    "date": match.group("date"),
                    "kind": kind,
                    "message": _sanitize(message),
                    "ts": ts,
                }
            )
    rows.sort(key=lambda r: (r["date"], r["dir"], r["agent"]))
    return rows


def emit(
    live_dir: Path | Sequence[Path], *, date: str, days_back: int, output: Path
) -> dict[str, object]:
    dirs = [live_dir] if isinstance(live_dir, Path) else list(live_dir)
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "window_end": date,
        "window_days": days_back,
        "scanned_dirs": [d.as_posix() for d in dirs],
        "markers": collect_markers(dirs, date=date, days_back=days_back),
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
    # Repeatable: the marker population spans three directories (K5). A single
    # default would silently re-create the blind spot for any caller that
    # forgets the other two, so the default IS the full measured population.
    emit_p.add_argument(
        "--live-dir",
        type=Path,
        action="append",
        dest="live_dirs",
        default=None,
        help="marker directory; repeatable (default: the full MARKER_DIRS population)",
    )
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
            args.live_dirs or list(MARKER_DIRS),
            date=args.date,
            days_back=args.days_back,
            output=args.output,
        )
        print(
            json.dumps(
                {
                    "emitted": len(summary["markers"]),
                    "scanned_dirs": summary["scanned_dirs"],
                    "output": str(args.output),
                }
            )
        )
        return 0
    return check(args.summary, date=args.date)


if __name__ == "__main__":
    raise SystemExit(main())
