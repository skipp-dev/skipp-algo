"""Render a weekly trend digest from a Plan 2.8 history JSONL.

Reads the long-running snapshot file written by
``scripts/plan_2_8_history_archive.py`` and produces a compact
markdown report comparing the most-recent snapshot against the one
``--lookback-days`` ago (default 7). The report includes:

  * coverage (snapshots in window, scoring roots),
  * per-TF aggregate HR/event drift,
  * per-TF x per-family HR drift, only for slices where both endpoints
    had >= ``--min-events`` events (default 30),
  * a short flag list for slices whose absolute drift exceeds
    ``--alert-threshold-pp`` (default 0.05).

Pure stdlib; meant to be wired into a weekly workflow that uploads
the markdown as an artifact and posts it to the run summary.

Exit codes
----------
  0 = digest written
  1 = unreadable history or empty window
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
    # Snapshots are written with the ``Z`` suffix.
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(ts)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"history not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _pick_endpoints(
    snapshots: list[dict[str, Any]],
    *,
    lookback_days: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(prev, latest)`` snapshots for the digest window.

    ``latest`` = newest snapshot.
    ``prev``   = newest snapshot whose ``captured_at`` is at least
                 ``lookback_days`` before ``latest``. ``None`` when no
                 such snapshot exists yet (e.g. history younger than
                 the window).
    """
    if not snapshots:
        return (None, None)
    sorted_snaps = sorted(snapshots, key=lambda s: s.get("captured_at", ""))
    latest = sorted_snaps[-1]
    cutoff = _parse_iso(latest["captured_at"]) - _dt.timedelta(days=lookback_days)
    prev: dict[str, Any] | None = None
    for snap in sorted_snaps[:-1]:
        try:
            ts = _parse_iso(snap["captured_at"])
        except (KeyError, ValueError):
            continue
        if ts <= cutoff:
            prev = snap  # keep the newest one that still satisfies the cutoff
    return (prev, latest)


def build_digest(
    *,
    snapshots: list[dict[str, Any]],
    lookback_days: int = 7,
    min_events: int = 30,
    alert_threshold_pp: float = 0.05,
) -> dict[str, Any]:
    prev, latest = _pick_endpoints(snapshots, lookback_days=lookback_days)
    if latest is None:
        return {
            "schema_version": 1,
            "status": "empty",
            "snapshots_total": 0,
            "lookback_days": lookback_days,
        }

    coverage = {
        "snapshots_total": len(snapshots),
        "lookback_days": lookback_days,
        "latest_captured_at": latest.get("captured_at"),
        "previous_captured_at": (prev or {}).get("captured_at"),
        "scoring_roots_in_window": sorted({
            s.get("scoring_root", "")
            for s in snapshots
            if prev is None or _parse_iso(s["captured_at"]) >= _parse_iso(prev["captured_at"])
        }),
    }

    if prev is None:
        return {
            "schema_version": 1,
            "status": "warmup",  # not enough history to compare
            "coverage": coverage,
            "per_tf": [],
            "per_family": [],
            "alerts": [],
        }

    latest_per_tf = latest.get("per_tf") or {}
    prev_per_tf = prev.get("per_tf") or {}

    per_tf_rows: list[dict[str, Any]] = []
    per_family_rows: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for tf in sorted(set(latest_per_tf) | set(prev_per_tf)):
        l_slot = latest_per_tf.get(tf) or {}
        p_slot = prev_per_tf.get(tf) or {}
        l_n = int(l_slot.get("n_events") or 0)
        p_n = int(p_slot.get("n_events") or 0)
        l_hr = float(l_slot.get("hit_rate") or 0.0)
        p_hr = float(p_slot.get("hit_rate") or 0.0)
        per_tf_rows.append({
            "tf": tf,
            "n_events_prev": p_n, "n_events_latest": l_n,
            "hr_prev": p_hr, "hr_latest": l_hr,
            "delta_pp": l_hr - p_hr,
            "comparable": l_n >= min_events and p_n >= min_events,
        })

        l_fams = (l_slot.get("families") or {})
        p_fams = (p_slot.get("families") or {})
        for fam in sorted(set(l_fams) | set(p_fams)):
            lf = l_fams.get(fam) or {}
            pf = p_fams.get(fam) or {}
            lfn = int(lf.get("n_events") or 0)
            pfn = int(pf.get("n_events") or 0)
            lfhr = float(lf.get("hit_rate") or 0.0)
            pfhr = float(pf.get("hit_rate") or 0.0)
            comparable = lfn >= min_events and pfn >= min_events
            row = {
                "tf": tf, "family": fam,
                "n_events_prev": pfn, "n_events_latest": lfn,
                "hr_prev": pfhr, "hr_latest": lfhr,
                "delta_pp": lfhr - pfhr,
                "comparable": comparable,
            }
            per_family_rows.append(row)
            if comparable and abs(row["delta_pp"]) >= alert_threshold_pp:
                alerts.append({
                    "tf": tf, "family": fam,
                    "delta_pp": row["delta_pp"],
                    "hr_prev": pfhr, "hr_latest": lfhr,
                })

    return {
        "schema_version": 1,
        "status": "ok",
        "coverage": coverage,
        "thresholds": {
            "min_events": min_events,
            "alert_threshold_pp": alert_threshold_pp,
        },
        "per_tf": per_tf_rows,
        "per_family": per_family_rows,
        "alerts": alerts,
    }


def render_markdown(digest: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Plan 2.8 weekly trend digest")
    lines.append("")
    status = digest.get("status", "?")
    lines.append(f"status: **{status}**")
    if status == "empty":
        lines.append("")
        lines.append("_(history file is empty; nothing to compare)_")
        return "\n".join(lines) + "\n"

    cov = digest.get("coverage", {})
    lines.append("")
    lines.append(f"- snapshots_total: {cov.get('snapshots_total')}")
    lines.append(f"- lookback_days: {cov.get('lookback_days')}")
    lines.append(f"- previous: `{cov.get('previous_captured_at') or '-'}`")
    lines.append(f"- latest:   `{cov.get('latest_captured_at') or '-'}`")

    if status == "warmup":
        lines.append("")
        lines.append("_(no snapshot old enough to compare against; "
                     "skipping per-TF and per-family tables)_")
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append("## Per-TF drift")
    lines.append("")
    lines.append("| TF | n_prev | n_latest | hr_prev | hr_latest | delta_pp | comparable |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | :---: |")
    for r in digest["per_tf"]:
        lines.append(
            f"| `{r['tf']}` | {r['n_events_prev']} | {r['n_events_latest']} | "
            f"{r['hr_prev']:.3f} | {r['hr_latest']:.3f} | "
            f"{r['delta_pp']:+.3f} | {'yes' if r['comparable'] else 'no'} |"
        )

    lines.append("")
    lines.append("## Per-TF x family drift")
    lines.append("")
    lines.append("| TF | family | n_prev | n_latest | hr_prev | hr_latest | delta_pp | comparable |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | :---: |")
    for r in digest["per_family"]:
        lines.append(
            f"| `{r['tf']}` | `{r['family']}` | {r['n_events_prev']} | "
            f"{r['n_events_latest']} | {r['hr_prev']:.3f} | "
            f"{r['hr_latest']:.3f} | {r['delta_pp']:+.3f} | "
            f"{'yes' if r['comparable'] else 'no'} |"
        )

    lines.append("")
    lines.append("## Alerts")
    lines.append("")
    if digest["alerts"]:
        for a in digest["alerts"]:
            lines.append(
                f"- `{a['tf']}/{a['family']}` drift {a['delta_pp']:+.3f} "
                f"(hr_prev={a['hr_prev']:.3f}, hr_latest={a['hr_latest']:.3f})"
            )
    else:
        lines.append("- _none_ (all comparable slices within threshold)")
    return "\n".join(lines) + "\n"


def render_issue_body(digest: dict[str, Any], *, run_url: str | None = None) -> str:
    """Render a compact GitHub-issue body for the alerts list.

    Designed to be piped through ``gh issue create --body-file -``
    by the weekly-digest workflow when ``digest['alerts']`` is
    non-empty. The body is intentionally short: title-worthy summary,
    each alert as one bullet, plus a closing pointer to the full
    digest artifact and (optionally) the workflow run URL.
    """
    alerts = digest.get("alerts") or []
    cov = digest.get("coverage") or {}
    thresholds = digest.get("thresholds") or {}
    lines: list[str] = []
    lines.append("# Plan 2.8 weekly digest - drift alerts")
    lines.append("")
    lines.append(f"- alerts: **{len(alerts)}**")
    lines.append(f"- previous snapshot: `{cov.get('previous_captured_at') or '-'}`")
    lines.append(f"- latest snapshot:   `{cov.get('latest_captured_at') or '-'}`")
    lines.append(f"- threshold (pp):    {thresholds.get('alert_threshold_pp')}")
    lines.append(f"- min_events floor:  {thresholds.get('min_events')}")
    lines.append("")
    lines.append("## Slices over threshold")
    lines.append("")
    for a in alerts:
        lines.append(
            f"- `{a['tf']}/{a['family']}` drift {a['delta_pp']:+.3f} "
            f"(hr_prev={a['hr_prev']:.3f}, hr_latest={a['hr_latest']:.3f})"
        )
    lines.append("")
    lines.append(
        "See the `plan-2-8-weekly-digest` workflow artifact for the full "
        "per-TF and per-family drift tables."
    )
    if run_url:
        lines.append("")
        lines.append(f"Workflow run: {run_url}")
    return "\n".join(lines) + "\n"


def has_alerts(digest: dict[str, Any]) -> bool:
    return bool(digest.get("alerts"))

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
        description="Render a weekly trend digest from a Plan 2.8 history JSONL.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--min-events", type=int, default=30)
    parser.add_argument("--alert-threshold-pp", type=float, default=0.05)
    parser.add_argument("--output", type=Path, default=None,
                        help="Write the rendered body to this path.")
    parser.add_argument("--format", choices=("md", "json", "issue"), default="md",
                        help="'md' = full digest, 'json' = raw verdict, "
                             "'issue' = compact GitHub-issue body for alerts.")
    parser.add_argument("--alerts-file", type=Path, default=None,
                        help="If given, write a JSON file whose 'has_alerts' "
                             "key indicates whether at least one comparable "
                             "slice crossed the threshold (used by CI gating).")
    parser.add_argument("--run-url", type=str, default=None,
                        help="Optional workflow-run URL appended to issue body.")
    args = parser.parse_args(argv)

    try:
        snapshots = _read_jsonl(args.history)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    digest = build_digest(
        snapshots=snapshots,
        lookback_days=args.lookback_days,
        min_events=args.min_events,
        alert_threshold_pp=args.alert_threshold_pp,
    )
    if args.format == "md":
        body = render_markdown(digest)
    elif args.format == "issue":
        body = render_issue_body(digest, run_url=args.run_url)
    else:
        body = json.dumps(digest, indent=2) + "\n"

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    if args.alerts_file is not None:
        args.alerts_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps({"has_alerts": has_alerts(digest),
                        "count": len(digest.get("alerts") or [])}, indent=2)
            + "\n", args.alerts_file)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
