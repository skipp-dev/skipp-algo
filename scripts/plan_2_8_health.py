"""Plan 2.8 rollout health aggregator.

Reads the JSON payloads the weekly/monthly digest helpers already
emit and produces a single ``health.json`` summary:

  - digest.json      (scripts/plan_2_8_trend_digest.py --format json)
  - coverage.json    (scripts/plan_2_8_coverage.py --format json)
  - stability.json   (scripts/plan_2_8_history_stability.py --format json)

Any missing input is treated as "unknown" for that axis. The output
collapses findings into a single 0..1 score + a list of human-readable
findings, so a status sidebar can render a one-glance verdict without
re-parsing each helper's shape.

Scoring is rule-based and intentionally simple:

  score = 1.0 - 0.50 * has_drift_alerts
              - 0.25 * has_coverage_gaps
              - 0.25 * has_unstable_slices

All subtractions floor to 0.0. ``status`` is derived from the score:

    score >= 0.9  -> "green"
    score >= 0.5  -> "amber"
    else          -> "red"

Pure stdlib, read-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _load(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def assess(
    digest: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    stability: dict[str, Any] | None,
) -> dict[str, Any]:
    findings: list[str] = []
    inputs_seen = {"digest": digest is not None,
                   "coverage": coverage is not None,
                   "stability": stability is not None}

    # Digest alerts.
    alerts = (digest or {}).get("alerts") or []
    alert_count = len(alerts)
    has_alerts = alert_count > 0
    if has_alerts:
        findings.append(f"{alert_count} drift alert(s) above threshold")

    # Coverage — any slice below min_events?
    under = (coverage or {}).get("counts", {}).get("under") or 0
    has_gap = under > 0
    if has_gap:
        findings.append(f"{under} slice(s) below coverage floor")

    # Stability — any unstable slice?
    unstable = (stability or {}).get("counts", {}).get("unstable") or 0
    has_unstable = unstable > 0
    if has_unstable:
        findings.append(f"{unstable} slice(s) jittering above stddev threshold")

    score = 1.0
    if has_alerts:
        score -= 0.50
    if has_gap:
        score -= 0.25
    if has_unstable:
        score -= 0.25
    score = max(0.0, round(score, 4))

    if score >= 0.9:
        status = "green"
    elif score >= 0.5:
        status = "amber"
    else:
        status = "red"

    return {
        "schema_version": 1,
        "status":          status,
        "score":           score,
        "findings":        findings,
        "inputs_seen":     inputs_seen,
        "signals": {
            "alerts":  alert_count,
            "under":   under,
            "unstable": unstable,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 rollout health"]
    lines.append("")
    lines.append(f"_status:_ **{report['status']}**  "
                 f"(score {report['score']:.2f})")
    lines.append("")
    sig = report["signals"]
    lines.append(f"- drift alerts:    {sig['alerts']}")
    lines.append(f"- coverage gaps:   {sig['under']}")
    lines.append(f"- unstable slices: {sig['unstable']}")
    lines.append("")
    missing = [k for k, v in report["inputs_seen"].items() if not v]
    if missing:
        lines.append(f"_missing inputs:_ {', '.join(sorted(missing))}")
        lines.append("")
    if report["findings"]:
        lines.append("## Findings")
        lines.append("")
        for f in report["findings"]:
            lines.append(f"- {f}")
    else:
        lines.append("No findings. Everything within bounds.")
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
        description="Aggregate Plan 2.8 digest/coverage/stability into a "
                    "rollout-health summary.",
    )
    parser.add_argument("--digest", type=Path, default=None)
    parser.add_argument("--coverage", type=Path, default=None)
    parser.add_argument("--stability", type=Path, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-red", action="store_true")
    args = parser.parse_args(argv)

    report = assess(
        _load(args.digest),
        _load(args.coverage),
        _load(args.stability),
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_red and report["status"] == "red":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
