"""ADR-0023 Stage-1 weekly judgement over the move-size shadow ledger.

The daily shadow runner (``scripts/run_magnitude_shadow_ledger.py``) records one
PASS / FAIL / INCONCLUSIVE row per family per day. Daily verdicts are noisy, so
the *decision* is made weekly (handover §4.4): for each family we look at the
trailing ``n`` evaluations and require ``k`` of them to PASS before the family
is considered Stage-2 eligible.

This module is **read-only**: it consumes the append-only ledger and emits a
judgement. It changes nothing in the promotion gate and arms nothing — it is the
weekly half of the Stage-1 shadow phase.

Roles (handover §3/§4.4)
------------------------
* ``BOS`` / ``SWEEP`` are **candidates**: healthy = k-of-n PASS *and* the AUC
  CI-low is not trending toward the 0.55 floor.
* ``FVG`` / ``OB`` are the **negative control**: healthy = stays below the bar
  (no PASS in the window).

Red flag (handover §4.4)
------------------------
If **all four families PASS on the latest date**, that is a data/pipeline
artifact signature, not skill — the run is flagged and no family is reported
eligible regardless of its streak.

Exit codes
----------
* ``0`` -- evaluated cleanly (eligible set may be empty; that is normal).
* ``2`` -- the all-four-PASS red flag fired on the latest date.
* ``3`` -- the ledger is empty / unreadable (nothing to judge).
* ``1`` -- usage/config error.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any

from governance.magnitude_resolution_gate import MAG_AUC_CI_LOW_FLOOR
from scripts.run_magnitude_shadow_ledger import (
    CANDIDATE_FAMILIES,
    DEFAULT_LEDGER,
    load_ledger,
)

# Weekly k-of-n defaults (handover §4.4: "n = last 4 weekly evaluations, k ≥ 3").
WEEKLY_N_DEFAULT = 4
WEEKLY_K_DEFAULT = 3

# CI-low is "trending toward the floor" when it is both falling across the
# window and sitting within this margin above MAG_AUC_CI_LOW_FLOOR (0.55).
CI_LOW_MARGIN = 0.02

# Sparkline anchoring range: 0.50 is a coin-flip (worthless), 0.70 is a strong
# move-size signal. Readings are clamped into this band before quantising.
SPARK_LO = 0.50
SPARK_HI = 0.70
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
_SPARK_GAP = "·"


def sparkline(values: list[Any], *, lo: float = SPARK_LO, hi: float = SPARK_HI) -> str:
    """Render a numeric series as a unicode block sparkline.

    Values are clamped into ``[lo, hi]`` then quantised onto the eight block
    glyphs. Non-numeric / missing readings render as a gap dot so the column
    width still matches the window length. An empty series renders ``""``.
    """
    if hi <= lo:
        raise ValueError("require lo < hi")
    out: list[str] = []
    span = hi - lo
    last = len(_SPARK_BLOCKS) - 1
    for v in values:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            out.append(_SPARK_GAP)
            continue
        clamped = min(hi, max(lo, float(v)))
        idx = round((clamped - lo) / span * last)
        out.append(_SPARK_BLOCKS[idx])
    return "".join(out)


def group_by_family(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group ledger rows by family, each list sorted ascending by date."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        family = row.get("family")
        if isinstance(family, str):
            grouped[family].append(row)
    for family in grouped:
        grouped[family].sort(key=lambda r: str(r.get("date")))
    return dict(grouped)


def _latest_date(rows: list[dict[str, Any]]) -> str | None:
    dates = [str(r.get("date")) for r in rows if r.get("date") is not None]
    return max(dates) if dates else None


def _ci_low_trends_to_floor(window: list[dict[str, Any]]) -> bool:
    """True when the AUC CI-low is falling *and* near the 0.55 floor.

    Needs at least two readings to establish a direction. A single reading
    cannot trend, so it is treated as not-trending.
    """
    ci_lows = [
        r.get("auc_ci_low")
        for r in window
        if isinstance(r.get("auc_ci_low"), (int, float))
    ]
    if len(ci_lows) < 2:
        return False
    earliest, latest = ci_lows[0], ci_lows[-1]
    falling = latest < earliest
    near_floor = (latest - MAG_AUC_CI_LOW_FLOOR) < CI_LOW_MARGIN
    return bool(falling and near_floor)


def evaluate_family(
    family: str,
    rows: list[dict[str, Any]],
    *,
    k: int = WEEKLY_K_DEFAULT,
    n: int = WEEKLY_N_DEFAULT,
) -> dict[str, Any]:
    """k-of-n judgement for one family over its trailing ``n`` evaluations."""
    window = rows[-n:]
    pass_count = sum(1 for r in window if r.get("status") == "PASS")
    fail_count = sum(1 for r in window if r.get("status") == "FAIL")
    inconclusive_count = sum(1 for r in window if r.get("status") == "INCONCLUSIVE")
    is_candidate = family in CANDIDATE_FAMILIES

    latest = window[-1] if window else {}
    meets_k_of_n = pass_count >= k
    ci_low_trending = _ci_low_trends_to_floor(window)
    auc_window = [r.get("magnitude_auc") for r in window]

    if is_candidate:
        # A candidate is healthy when it clears k-of-n and its lower CI bound
        # is not sliding toward the floor.
        healthy = meets_k_of_n and not ci_low_trending
        stage2_eligible = healthy
    else:
        # A control is healthy when it stays below the bar (no PASS in window).
        healthy = pass_count == 0
        stage2_eligible = False

    return {
        "family": family,
        "role": "candidate" if is_candidate else "control",
        "window_size": len(window),
        "k_required": k,
        "n_window": n,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "inconclusive_count": inconclusive_count,
        "meets_k_of_n": meets_k_of_n,
        "ci_low_trending_to_floor": ci_low_trending,
        "latest_date": latest.get("date"),
        "latest_status": latest.get("status"),
        "latest_auc": latest.get("magnitude_auc"),
        "latest_ci_low": latest.get("auc_ci_low"),
        "auc_window": auc_window,
        "healthy": healthy,
        "stage2_eligible": stage2_eligible,
    }


def detect_all_pass_red_flag(rows: list[dict[str, Any]]) -> bool:
    """True when every family that reported on the latest date PASSED.

    Requires at least two families on that date (a single-family day is not an
    "all four pass" artifact signature).
    """
    latest = _latest_date(rows)
    if latest is None:
        return False
    latest_rows = [r for r in rows if str(r.get("date")) == latest]
    if len(latest_rows) < 2:
        return False
    return all(r.get("status") == "PASS" for r in latest_rows)


def evaluate_weekly(
    rows: list[dict[str, Any]],
    *,
    k: int = WEEKLY_K_DEFAULT,
    n: int = WEEKLY_N_DEFAULT,
) -> dict[str, Any]:
    """Full weekly report: per-family judgement + Stage-2 eligibility."""
    grouped = group_by_family(rows)
    families = {
        family: evaluate_family(family, family_rows, k=k, n=n)
        for family, family_rows in sorted(grouped.items())
    }
    red_flag = detect_all_pass_red_flag(rows)

    if red_flag:
        # An artifact-shaped run disqualifies the whole window: trust nothing.
        eligible: list[str] = []
    else:
        eligible = sorted(
            f for f, v in families.items() if v["stage2_eligible"]
        )

    return {
        "k_required": k,
        "n_window": n,
        "latest_date": _latest_date(rows),
        "all_pass_red_flag": red_flag,
        "families": families,
        "stage2_eligible": eligible,
    }


def render_text(report: dict[str, Any]) -> str:
    """Human-readable weekly summary (handover §4.5)."""
    lines: list[str] = []
    lines.append(
        f"ADR-0023 Stage-1 weekly judgement "
        f"(k={report['k_required']} of n={report['n_window']}, "
        f"latest={report['latest_date']})"
    )
    for family, v in report["families"].items():
        auc = v["latest_auc"]
        ci = v["latest_ci_low"]
        auc_s = f"{auc:.3f}" if isinstance(auc, (int, float)) else "n/a"
        ci_s = f"{ci:.3f}" if isinstance(ci, (int, float)) else "n/a"
        health = "healthy" if v["healthy"] else "ATTENTION"
        trend = " ci-low→floor" if v["ci_low_trending_to_floor"] else ""
        spark = sparkline(v.get("auc_window", []))
        spark_s = f" [{spark}]" if spark else ""
        lines.append(
            f"  {family:<6}[{v['role']:<9}] "
            f"pass {v['pass_count']}/{v['window_size']} "
            f"(need {v['k_required']}){spark_s} "
            f"AUC={auc_s} CIlow={ci_s} {health}{trend}"
        )
        if v["role"] == "candidate" and not v["stage2_eligible"]:
            remaining = max(0, v["k_required"] - v["pass_count"])
            if remaining > 0:
                lines.append(
                    f"         Stage-2 progress: {v['pass_count']}/"
                    f"{v['k_required']} PASS — needs {remaining} more"
                )
            elif v["ci_low_trending_to_floor"]:
                lines.append(
                    "         Stage-2 progress: k-of-n met but CI-low "
                    "trending to floor — blocked"
                )
    if report["all_pass_red_flag"]:
        lines.append(
            "  RED FLAG: all families PASSED on the latest date — suspected "
            "data/pipeline artifact; no family reported eligible."
        )
    eligible = report["stage2_eligible"]
    lines.append(
        "  Stage-2 eligible: " + (", ".join(eligible) if eligible else "none")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"shadow ledger JSONL path (default: {DEFAULT_LEDGER})",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=WEEKLY_K_DEFAULT,
        help=f"PASSes required within the window (default: {WEEKLY_K_DEFAULT})",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=WEEKLY_N_DEFAULT,
        help=f"trailing evaluations in the window (default: {WEEKLY_N_DEFAULT})",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    args = parser.parse_args(argv)

    if args.k < 1 or args.n < 1 or args.k > args.n:
        print("error: require 1 <= k <= n", file=sys.stderr)
        return 1

    rows = load_ledger(args.ledger)
    if not rows:
        print(f"error: empty or missing ledger: {args.ledger}", file=sys.stderr)
        return 3

    report = evaluate_weekly(rows, k=args.k, n=args.n)

    if args.format == "json":
        print(json.dumps(report, sort_keys=True, indent=2))
    else:
        print(render_text(report))

    return 2 if report["all_pass_red_flag"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
