"""F2 weekly (or N-day) digest of promotion-gate reports.

The §2.4 G3 30-day SPRT window operator review needs a single rolled-
up view of the daily promotion-gate reports (one file per day, named
``f2_promotion_gate_<YYYY-MM-DD>.json``). This helper scans the
reports directory, sorts by date, optionally trims to the last N days,
and emits:

  * A per-day timeline: ``[{date, decision, brier_delta, sprt_decision,
    sprt_n, sprt_k}, ...]``
  * Roll-up counters: ``decisions = {promote, hold, rollback,
    insufficient_data}``, ``sprt_decisions = {accept_h0, accept_h1,
    continue}``, ``consecutive_worse``, ``consecutive_better``.
  * Window metadata: ``window_days``, ``date_range = [first, last]``,
    ``len`` (number of reports inside the window).

Pure-Python, read-only, no network. Schema-pinned (``schema_version``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

DIGEST_SCHEMA_VERSION = 1
DEFAULT_WINDOW_DAYS = 7
_REPORT_RE = re.compile(r"f2_promotion_gate_(\d{4}-\d{2}-\d{2})\.json$")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _brier_delta(report: dict[str, Any]) -> float | None:
    """Extract the calibrated_brier delta (treatment - control) from
    the report's ``kpi_metrics`` block. Returns None if absent."""
    metrics = report.get("kpi_metrics") or []
    if not isinstance(metrics, list):
        return None
    for m in metrics:
        if isinstance(m, dict) and m.get("metric") == "calibrated_brier":
            d = m.get("delta")
            if isinstance(d, (int, float)):
                return float(d)
    return None


def _scan_reports(reports_dir: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if not reports_dir.exists():
        return out
    for p in reports_dir.iterdir():
        m = _REPORT_RE.search(p.name)
        if m:
            out.append((m.group(1), p))
    out.sort()
    return out


def _consecutive_count(values: list[float], *, worse: bool) -> int:
    """Trailing run of values matching the worse/better predicate."""
    n = 0
    for v in reversed(values):
        if (v > 0 if worse else v < 0):
            n += 1
        else:
            break
    return n


def build_digest(
    *,
    reports_dir: Path,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Build the rolled-up digest dict."""
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    if not reports_dir.exists():
        raise ValueError(f"reports-dir does not exist: {reports_dir}")

    all_reports = _scan_reports(reports_dir)
    windowed = all_reports[-window_days:] if window_days else all_reports

    timeline: list[dict[str, Any]] = []
    decisions: dict[str, int] = {}
    sprt_decisions: dict[str, int] = {}
    deltas: list[float] = []

    for date, path in windowed:
        try:
            report = _load_json(path)
        except (json.JSONDecodeError, OSError):
            timeline.append({
                "date": date, "path": str(path),
                "decision": None, "error": "unreadable",
            })
            continue
        decision = report.get("decision")
        decisions[str(decision)] = decisions.get(str(decision), 0) + 1
        sprt = report.get("sprt") or {}
        sprt_dec = sprt.get("decision") if isinstance(sprt, dict) else None
        if sprt_dec is not None:
            sprt_decisions[str(sprt_dec)] = sprt_decisions.get(str(sprt_dec), 0) + 1
        delta = _brier_delta(report)
        if delta is not None:
            deltas.append(delta)
        timeline.append({
            "date": date,
            "path": str(path),
            "decision": decision,
            "brier_delta": delta,
            "sprt_decision": sprt_dec,
            "sprt_n": sprt.get("n") if isinstance(sprt, dict) else None,
            "sprt_k": sprt.get("k") if isinstance(sprt, dict) else None,
        })

    date_range = (
        [windowed[0][0], windowed[-1][0]] if windowed else [None, None]
    )
    return {
        "schema_version": DIGEST_SCHEMA_VERSION,
        "reports_dir": str(reports_dir),
        "window_days": window_days,
        "date_range": date_range,
        "len": len(windowed),
        "total_reports_seen": len(all_reports),
        "timeline": timeline,
        "decisions": decisions,
        "sprt_decisions": sprt_decisions,
        "consecutive_worse": _consecutive_count(deltas, worse=True),
        "consecutive_better": _consecutive_count(deltas, worse=False),
    }


def render_markdown(digest: dict[str, Any]) -> str:
    """Operator-readable Markdown render of the digest."""
    lines: list[str] = []
    lines.append(f"# F2 weekly digest — last {digest.get('window_days')} days")
    lines.append("")
    rng = digest.get("date_range") or [None, None]
    lines.append(
        f"- **window**: `{rng[0]}` → `{rng[1]}` "
        f"({digest.get('len', 0)} reports in window, "
        f"{digest.get('total_reports_seen', 0)} total seen)"
    )
    decisions = digest.get("decisions") or {}
    if decisions:
        parts = ", ".join(f"`{k}`={v}" for k, v in sorted(decisions.items()))
        lines.append(f"- **decisions**: {parts}")
    sprt = digest.get("sprt_decisions") or {}
    if sprt:
        parts = ", ".join(f"`{k}`={v}" for k, v in sorted(sprt.items()))
        lines.append(f"- **SPRT**: {parts}")
    lines.append(f"- **consecutive worse**: {digest.get('consecutive_worse', 0)}")
    lines.append(f"- **consecutive better**: {digest.get('consecutive_better', 0)}")
    lines.append("")
    lines.append("## Timeline")
    lines.append("")
    lines.append("| date | decision | brier_delta | sprt | n | k |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for entry in digest.get("timeline") or []:
        d = entry.get("brier_delta")
        d_str = f"{d:+.6f}" if isinstance(d, (int, float)) else "—"
        lines.append(
            f"| `{entry.get('date', '?')}` "
            f"| `{entry.get('decision', '?')}` "
            f"| {d_str} "
            f"| `{entry.get('sprt_decision', '—')}` "
            f"| {entry.get('sprt_n', '—')} "
            f"| {entry.get('sprt_k', '—')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Roll up the last N days of F2 promotion-gate reports into a digest."
    )
    parser.add_argument("--reports-dir", type=Path, required=True,
                        help="Directory holding f2_promotion_gate_*.json files.")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"How many trailing days to include (default: {DEFAULT_WINDOW_DAYS}).")
    parser.add_argument("--format", choices=["json", "md"], default="json",
                        help="Output format (default: json).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional output path (always JSON).")
    args = parser.parse_args(argv)

    try:
        digest = build_digest(
            reports_dir=args.reports_dir,
            window_days=args.window_days,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(digest, indent=2) + "\n", args.output)
    if args.format == "md":
        print(render_markdown(digest))
    else:
        print(json.dumps(digest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
