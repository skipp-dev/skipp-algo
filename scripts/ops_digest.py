"""Daily ops digest -> Outlook email (use case #4).

Surfaces the handful of numbers the operator would otherwise have to fish for
by hand — the same numbers the date-gated calendar reminders wait on:

* **Sweep-trap shadow** (WS4a): sample count vs the 40-sample promotion gate and
  the current verdict (``artifacts/monitoring/sweep_trap_shadow.json``).
* **open_prep feature importance / FI-ledger**: labeled-sample count vs the
  200-sample auto-tune gate (``artifacts/open_prep/feature_importance/latest.json``).
* **Calibration**: public calibration status + weighted hit-rate
  (``docs/calibration/calibration_report_public.json``).

Each collector is independent and fail-soft: a missing or malformed artifact
becomes a "n/a" row, never a crash. The digest is delivered via the connected
Outlook account (``OUTLOOK_SEND_EMAIL``) to ``OPS_DIGEST_EMAIL_TO``.

Note on data availability: this reads artifacts present in a repo checkout /
CI workspace. Producer-volume-only files (e.g. the live calibration bucket
counts in ``/app/data/calibration_latest.json``) are NOT in the checkout, so
this digest reports the repo-published public calibration report instead and
says so — it does not pretend to see the live bucket detail.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:  # `python scripts/foo.py` puts scripts/ on sys.path[0]
    import composio_ops
    from smc_atomic_write import atomic_write_text
except ImportError:  # imported as scripts.ops_digest (pytest pythonpath=".")
    from scripts import composio_ops
    from scripts.smc_atomic_write import atomic_write_text


@dataclass
class Section:
    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


_VERDICT_LABELS = {0: "INCONCLUSIVE", 1: "SHADOW", 2: "PROMOTABLE"}


def collect_sweep_trap(root: Path) -> Section:
    section = Section("🪝 Sweep-Trap Shadow (WS4a)")
    data = _load_json(root / "artifacts/monitoring/sweep_trap_shadow.json")
    if data is None:
        section.note = "snapshot not found — no data accrued yet"
        return section
    n = data.get("n_samples")
    minimum = data.get("min_samples", 40)
    verdict = data.get("verdict") or _VERDICT_LABELS.get(data.get("verdict_code"))
    section.rows = [
        ("Samples", f"{_fmt(n)} / {_fmt(minimum)} gate"),
        ("Verdict", _fmt(verdict)),
        ("Brier delta", _fmt(data.get("brier_delta"))),
        ("Tercile lift", _fmt(data.get("lift"))),
    ]
    try:
        if n is not None and float(n) >= float(minimum) and str(verdict).upper() == "PROMOTABLE":
            section.note = "≥40 samples & PROMOTABLE — WS4b green light, check verdict_code."
        elif n is not None and float(n) < float(minimum):
            section.note = f"{float(minimum) - float(n):.0f} more samples needed to reach the gate."
    except (TypeError, ValueError):
        pass
    return section


def collect_feature_importance(root: Path) -> Section:
    section = Section("📊 open_prep Feature Importance (FI-ledger)")
    data = _load_json(root / "artifacts/open_prep/feature_importance/latest.json")
    if data is None:
        section.note = "latest.json not found"
        return section
    labeled = data.get("labeled_samples")
    gate = data.get("min_samples_threshold", 200)
    section.rows = [
        ("Labeled samples", f"{_fmt(labeled)} / {_fmt(gate)} auto-tune gate"),
        ("Lookback days", _fmt(data.get("lookback_days"))),
        ("Generated", _fmt(data.get("generated_at_et"))),
    ]
    drift = data.get("ranking_drift")
    if isinstance(drift, dict):
        drifted = drift.get("drifted_features")
        section.rows.append(
            ("Ranking drift", "none" if not drifted else f"{len(drifted)} feature(s)")
        )
    try:
        if labeled is not None and float(labeled) < float(gate):
            section.note = f"{float(gate) - float(labeled):.0f} more labeled samples to the 200 gate."
    except (TypeError, ValueError):
        pass
    return section


def collect_calibration(root: Path) -> Section:
    section = Section("🎯 Calibration (public report)")
    data = _load_json(root / "docs/calibration/calibration_report_public.json")
    if data is None:
        section.note = "public calibration report not found"
        return section
    families = data.get("family_weights")
    section.rows = [
        ("Status", _fmt(data.get("status"))),
        ("Weighted hit-rate", _fmt(data.get("weighted_hit_rate"))),
        ("Events", _fmt(data.get("n_events"))),
        ("Families weighted", _fmt(len(families) if isinstance(families, dict) else None)),
        ("Generated", _fmt(data.get("generated_at"))),
    ]
    section.note = (
        "Repo-published public report; live per-bucket arm-readiness lives on the "
        "producer volume (calibration_latest.json) and is not in the checkout."
    )
    return section


def build_sections(root: Path) -> list[Section]:
    return [
        collect_sweep_trap(root),
        collect_feature_importance(root),
        collect_calibration(root),
    ]


def render_html(sections: list[Section], *, generated_at: str) -> str:
    parts = [
        "<div style=\"font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
        "font-size:14px;color:#1a1a1a;max-width:640px\">",
        "<h2 style=\"margin:0 0 4px\">skipp-algo — Ops Digest</h2>",
        f"<p style=\"color:#666;margin:0 0 16px\">{generated_at}</p>",
    ]
    for sec in sections:
        parts.append(f"<h3 style=\"margin:18px 0 6px\">{sec.title}</h3>")
        if sec.rows:
            parts.append("<table style=\"border-collapse:collapse;width:100%\">")
            for label, value in sec.rows:
                parts.append(
                    "<tr>"
                    f"<td style=\"padding:3px 10px 3px 0;color:#555;white-space:nowrap\">{label}</td>"
                    f"<td style=\"padding:3px 0;font-weight:600\">{value}</td>"
                    "</tr>"
                )
            parts.append("</table>")
        if sec.note:
            parts.append(f"<p style=\"margin:4px 0 0;color:#777;font-style:italic\">{sec.note}</p>")
    parts.append(
        "<p style=\"color:#999;margin:20px 0 0;font-size:12px\">"
        "Automated via Composio (OUTLOOK_SEND_EMAIL). Reflects artifacts in the CI checkout.</p>"
    )
    parts.append("</div>")
    return "".join(parts)


def render_text(sections: list[Section], *, generated_at: str) -> str:
    lines = [f"skipp-algo — Ops Digest ({generated_at})", ""]
    for sec in sections:
        lines.append(sec.title)
        for label, value in sec.rows:
            lines.append(f"  {label}: {value}")
        if sec.note:
            lines.append(f"  -> {sec.note}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--root", default=".", help="Repo root to read artifacts from.")
    parser.add_argument(
        "--to",
        default=os.getenv("OPS_DIGEST_EMAIL_TO", ""),
        help="Recipient email (default: $OPS_DIGEST_EMAIL_TO).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render + print the digest but do not send it.",
    )
    parser.add_argument("--output", help="Also write the rendered HTML to this path.")
    args = parser.parse_args(argv)

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    sections = build_sections(Path(args.root))
    html = render_html(sections, generated_at=generated_at)
    text = render_text(sections, generated_at=generated_at)
    print(text)

    if args.output:
        atomic_write_text(html, args.output)

    if args.dry_run:
        print("ops_digest: --dry-run, not sending.")
        return 0

    subject = f"skipp-algo Ops Digest — {datetime.now(UTC).strftime('%Y-%m-%d')}"
    result = composio_ops.send_outlook_email(args.to, subject, html)
    if result.skipped:
        print(f"ops_digest: email skipped — {result.detail}")
    elif result.delivered:
        print(f"ops_digest: digest emailed to {args.to}.")
    else:
        # Best-effort ops notification (composio_ops contract): a Composio hiccup
        # must NOT red the ops-digest cron. Surface the error, exit green — same
        # always-0 discipline as the credential-health notify path.
        print(f"ops_digest: email FAILED — {result.detail}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
