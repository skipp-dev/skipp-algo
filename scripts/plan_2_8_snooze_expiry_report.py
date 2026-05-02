"""Plan 2.8 snooze expiry report.

Reads ``configs/plan_2_8_snoozes.json`` and categorises each entry
as:

  - ``expired``   — ``expires`` is in the past
  - ``expiring``  — ``expires`` is within the next ``--within-days``
  - ``active``    — ``expires`` further in the future
  - ``permanent`` — no ``expires`` field

Output is either a human-readable markdown summary (default) or a
JSON payload suitable for dashboards.

Entries with unparseable ``expires`` are reported in a ``malformed``
bucket rather than crashing. Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _parse_date(s: Any) -> _dt.date | None:
    if not isinstance(s, str) or not s:
        return None
    head = s[:10]
    try:
        return _dt.date.fromisoformat(head)
    except ValueError:
        return None


def categorise(
    entries: list[dict[str, Any]],
    *,
    within_days: int = 14,
    today: _dt.date | None = None,
) -> dict[str, Any]:
    today_ = today or _dt.date.today()
    soon_floor = today_ + _dt.timedelta(days=within_days)

    expired: list[dict[str, Any]] = []
    expiring: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    permanent: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []

    for e in entries:
        raw = e.get("expires")
        if raw in (None, ""):
            permanent.append(e)
            continue
        d = _parse_date(raw)
        if d is None:
            malformed.append(e)
            continue
        if d < today_:
            expired.append(e)
        elif d <= soon_floor:
            expiring.append(e)
        else:
            active.append(e)

    def _sort_key(x: dict[str, Any]) -> tuple[str, str, str]:
        return (str(x.get("expires", "")),
                str(x.get("tf", "")),
                str(x.get("family", "")))

    return {
        "schema_version": 1,
        "today":           today_.isoformat(),
        "within_days":     within_days,
        "counts": {
            "expired":   len(expired),
            "expiring":  len(expiring),
            "active":    len(active),
            "permanent": len(permanent),
            "malformed": len(malformed),
            "total":     len(entries),
        },
        "expired":   sorted(expired, key=_sort_key),
        "expiring":  sorted(expiring, key=_sort_key),
        "active":    sorted(active, key=_sort_key),
        "permanent": sorted(permanent, key=_sort_key),
        "malformed": malformed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 snooze expiry report",
        "",
        f"_today:_ `{report['today']}`  |  "
        f"_horizon:_ {report['within_days']} days",
        "",
        f"- expired:    {c['expired']}",
        f"- expiring:   {c['expiring']}",
        f"- active:     {c['active']}",
        f"- permanent:  {c['permanent']}",
        f"- malformed:  {c['malformed']}",
        "",
    ]
    for bucket in ("expired", "expiring"):
        rows = report[bucket]
        lines.append(f"## {bucket.title()} ({len(rows)})")
        lines.append("")
        if not rows:
            lines.append("_none_")
            lines.append("")
            continue
        lines.append("| expires | tf | family | reason |")
        lines.append("| --- | --- | --- | --- |")
        for r in rows:
            lines.append(
                f"| {r.get('expires', '')} | {r.get('tf', '')} | "
                f"{r.get('family', '')} | {r.get('reason', '')} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    snoozes = data.get("snoozes")
    if not isinstance(snoozes, list):
        return []
    return [e for e in snoozes if isinstance(e, dict)]

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
        description="Report Plan 2.8 snooze entries that are expired or "
                    "expiring soon.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--within-days", type=int, default=14)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-expired", action="store_true")
    args = parser.parse_args(argv)

    try:
        entries = _load(args.config)
    except FileNotFoundError:
        print(f"ERROR: config not found: {args.config}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: config is not valid JSON: {exc}", file=sys.stderr)
        return 1

    report = categorise(entries, within_days=args.within_days)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_expired and report["counts"]["expired"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
