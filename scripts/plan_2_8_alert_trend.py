"""Plan 2.8 alert trend aggregator.

Aggregates a directory of archived digest JSONs (produced by
``scripts/plan_2_8_digest_archive.py``) into a per-``(tf, family)``
trend record. The latest two archives are used by default:

  - ``latest`` = the most recent digest by ``captured_at`` (ISO)
  - ``prev``   = the one directly before it (if any)

For every alert key seen in *either* archive, the record exposes:

  - latest/prev ``events``, ``hit_rate_pct``, ``delta_pp``
  - deltas (``events_delta``, ``hit_rate_delta``)
  - ``direction``: ``rising`` | ``falling`` | ``flat`` | ``new`` |
    ``gone``

Pure stdlib. Tolerant of missing or malformed archives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

FLAT_EPS = 1e-9


def _load_archive(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _latest_two(archive_dir: Path) -> list[Path]:
    if not archive_dir.exists():
        return []
    files = sorted(archive_dir.glob("*.json"))
    return files[-2:]


def _index(digest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    alerts = digest.get("alerts")
    if not isinstance(alerts, list):
        return out
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        tf = alert.get("tf")
        fam = alert.get("family")
        if not isinstance(tf, str) or not isinstance(fam, str):
            continue
        out[(tf, fam)] = alert
    return out


def _direction(
    latest: dict[str, Any] | None,
    prev: dict[str, Any] | None,
) -> str:
    if latest is None:
        return "gone"
    if prev is None:
        return "new"
    try:
        delta = float(latest.get("hit_rate_pct", 0.0)) \
            - float(prev.get("hit_rate_pct", 0.0))
    except (TypeError, ValueError):
        return "flat"
    if abs(delta) < FLAT_EPS:
        return "flat"
    return "rising" if delta > 0 else "falling"


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def build(
    latest: dict[str, Any] | None,
    prev: dict[str, Any] | None,
) -> dict[str, Any]:
    l_idx = _index(latest) if isinstance(latest, dict) else {}
    p_idx = _index(prev) if isinstance(prev, dict) else {}
    keys = sorted(set(l_idx) | set(p_idx))

    entries: list[dict[str, Any]] = []
    direction_counts = {"rising": 0, "falling": 0, "flat": 0,
                        "new": 0, "gone": 0}
    for tf, fam in keys:
        lat = l_idx.get((tf, fam))
        p = p_idx.get((tf, fam))
        direction = _direction(lat, p)
        direction_counts[direction] += 1

        l_hr = _num((lat or {}).get("hit_rate_pct"))
        p_hr = _num((p or {}).get("hit_rate_pct"))
        l_ev = _num((lat or {}).get("events"))
        p_ev = _num((p or {}).get("events"))

        def _delta(a: float | None, b: float | None) -> float | None:
            if a is None or b is None:
                return None
            return a - b

        entries.append({
            "tf":              tf,
            "family":          fam,
            "latest_events":   l_ev,
            "prev_events":     p_ev,
            "events_delta":    _delta(l_ev, p_ev),
            "latest_hit_rate": l_hr,
            "prev_hit_rate":   p_hr,
            "hit_rate_delta":  _delta(l_hr, p_hr),
            "direction":       direction,
        })

    return {
        "schema_version":   1,
        "latest_captured":  (latest or {}).get("captured_at"),
        "prev_captured":    (prev or {}).get("captured_at"),
        "counts": {
            "entries": len(entries),
            **direction_counts,
        },
        "entries": entries,
    }


def _fmt_num(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 alert trend",
        "",
        f"- latest captured: `{report.get('latest_captured') or '-'}`",
        f"- prev captured:   `{report.get('prev_captured') or '-'}`",
        f"- entries:         {c['entries']}",
        f"- rising / falling / flat: "
        f"{c['rising']} / {c['falling']} / {c['flat']}",
        f"- new / gone:      {c['new']} / {c['gone']}",
        "",
    ]
    if not report["entries"]:
        lines.append("_No alerts tracked._")
        return "\n".join(lines) + "\n"
    lines.append(
        "| tf | family | latest ev | prev ev | delta ev | "
        "latest hr | prev hr | delta hr | direction |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for e in report["entries"]:
        lines.append(
            "| "
            + " | ".join([
                e["tf"], e["family"],
                _fmt_num(e["latest_events"]),
                _fmt_num(e["prev_events"]),
                _fmt_num(e["events_delta"]),
                _fmt_num(e["latest_hit_rate"]),
                _fmt_num(e["prev_hit_rate"]),
                _fmt_num(e["hit_rate_delta"]),
                e["direction"],
            ])
            + " |"
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
        description="Build a Plan 2.8 alert trend report from the "
                    "latest two archived digests.",
    )
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-empty", action="store_true")
    args = parser.parse_args(argv)

    if not args.archive_dir.exists():
        print(f"ERROR: archive-dir not found: {args.archive_dir}",
              file=sys.stderr)
        return 1
    files = _latest_two(args.archive_dir)
    latest = _load_archive(files[-1]) if files else None
    prev = _load_archive(files[-2]) if len(files) >= 2 else None
    report = build(latest, prev)

    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_empty and report["counts"]["entries"] == 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
