"""Q4-Gate evaluator for Plan 2.8 §3.2 (4th HTF trend layer, 2H candidate).

Addendum 2.8 §3.2 defines three cumulative gates that must ALL pass
before a 2H 4th trend layer may be promoted over the 3-TF baseline:

  G1. ``A/B hit-rate uplift >= 3pp in >= 2 of the 3 tested context
      buckets (RTH/ETH x NORMAL/HIGH-VOL x LONG/SHORT-BIAS).``
  G2. ``Brier regression <= 0.02`` (no calibration degradation).
  G3. ``Per-bucket events >= 30`` after promotion (Blasiok & Nakkiran
      2023 smECE floor).

This helper consumes a Q4-gate input bundle (A/B per-bucket stats +
overall Brier + per-bucket event counts) and emits a structured
verdict. It does not mutate anything; it is a pure evaluator used at
the W13 operator review.

The input schema is minimal on purpose — callers are free to build it
from any A/B framework (Phase-G-Framework output, custom harness, etc.).

Exit codes
----------
  0 = verdict generated (regardless of gate outcome)
  1 = input JSON invalid or gate parameters out of range
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

GATE_SCHEMA_VERSION = 1

DEFAULT_UPLIFT_MIN_PP = 0.03        # 3 percentage points
DEFAULT_UPLIFT_MIN_BUCKETS = 2
DEFAULT_BRIER_MAX_REGRESSION = 0.02
DEFAULT_MIN_EVENTS_PER_BUCKET = 30


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"unreadable input bundle {path}: {exc}") from exc


def evaluate_gate(
    bundle: dict[str, Any],
    *,
    uplift_min_pp: float = DEFAULT_UPLIFT_MIN_PP,
    uplift_min_buckets: int = DEFAULT_UPLIFT_MIN_BUCKETS,
    brier_max_regression: float = DEFAULT_BRIER_MAX_REGRESSION,
    min_events_per_bucket: int = DEFAULT_MIN_EVENTS_PER_BUCKET,
) -> dict[str, Any]:
    """Evaluate the three §3.2 Q4 gates against the given bundle.

    Expected bundle schema (top-level keys):

      ``buckets``: list of objects, each with:
          ``key``        — str (bucket id, e.g. "RTH/NORMAL/LONG"),
          ``hr_baseline`` — float (3-TF arm hit rate, 0.0..1.0),
          ``hr_candidate`` — float (4-TF arm hit rate, 0.0..1.0),
          ``n_events``    — int (events in this bucket, treatment-arm).
      ``brier_baseline``  — float (aggregate 3-TF-arm Brier score).
      ``brier_candidate`` — float (aggregate 4-TF-arm Brier score).

    Returns a schema_version=1 verdict dict.
    """
    if uplift_min_buckets < 1:
        raise ValueError("uplift_min_buckets must be >= 1")
    if min_events_per_bucket < 0:
        raise ValueError("min_events_per_bucket must be >= 0")

    raw_buckets = bundle.get("buckets") or []
    if not isinstance(raw_buckets, list):
        raise ValueError("bundle['buckets'] must be a list")

    bucket_results: list[dict[str, Any]] = []
    for b in raw_buckets:
        if not isinstance(b, dict):
            raise ValueError("each bucket must be a dict")
        key = str(b.get("key") or "")
        hr_b = float(b.get("hr_baseline") or 0.0)
        hr_c = float(b.get("hr_candidate") or 0.0)
        n = int(b.get("n_events") or 0)
        delta = hr_c - hr_b
        bucket_results.append({
            "key": key,
            "hr_baseline": hr_b,
            "hr_candidate": hr_c,
            "delta_pp": delta,
            "n_events": n,
            "uplift_ok": delta >= uplift_min_pp,
            "events_ok": n >= min_events_per_bucket,
        })

    uplift_buckets = [b for b in bucket_results if b["uplift_ok"]]
    events_buckets = [b for b in bucket_results if not b["events_ok"]]

    brier_baseline = float(bundle.get("brier_baseline") or 0.0)
    brier_candidate = float(bundle.get("brier_candidate") or 0.0)
    brier_regression = brier_candidate - brier_baseline

    gates = {
        "G1_uplift": {
            "passed": len(uplift_buckets) >= uplift_min_buckets,
            "requirement": f">= {uplift_min_buckets} buckets with delta_pp >= {uplift_min_pp}",
            "uplift_buckets": [b["key"] for b in uplift_buckets],
            "uplift_bucket_count": len(uplift_buckets),
        },
        "G2_brier": {
            "passed": brier_regression <= brier_max_regression,
            "requirement": f"brier_candidate - brier_baseline <= {brier_max_regression}",
            "brier_regression": brier_regression,
        },
        "G3_min_events": {
            "passed": len(events_buckets) == 0,
            "requirement": f"every bucket has n_events >= {min_events_per_bucket}",
            "under_threshold_buckets": [b["key"] for b in events_buckets],
        },
    }
    all_passed = all(g["passed"] for g in gates.values())
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "overall": "pass" if all_passed else "fail",
        "gates": gates,
        "thresholds": {
            "uplift_min_pp": uplift_min_pp,
            "uplift_min_buckets": uplift_min_buckets,
            "brier_max_regression": brier_max_regression,
            "min_events_per_bucket": min_events_per_bucket,
        },
        "brier": {
            "baseline": brier_baseline,
            "candidate": brier_candidate,
            "regression": brier_regression,
        },
        "buckets": bucket_results,
    }


def render_markdown(verdict: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Plan 2.8 Q4-Gate verdict")
    lines.append("")
    lines.append(f"**overall: `{verdict['overall']}`**")
    lines.append("")
    lines.append("## Gates")
    lines.append("")
    lines.append("| gate | passed | requirement |")
    lines.append("| --- | :---: | --- |")
    for name, g in verdict["gates"].items():
        passed = "yes" if g["passed"] else "no"
        lines.append(f"| `{name}` | {passed} | {g['requirement']} |")
    lines.append("")
    lines.append("## Brier")
    lines.append("")
    br = verdict["brier"]
    lines.append(f"- baseline: {br['baseline']:.4f}")
    lines.append(f"- candidate: {br['candidate']:.4f}")
    lines.append(f"- regression: {br['regression']:+.4f}")
    lines.append("")
    lines.append("## Buckets")
    lines.append("")
    lines.append("| key | hr_base | hr_cand | delta_pp | n | uplift | events |")
    lines.append("| --- | ---: | ---: | ---: | ---: | :---: | :---: |")
    for b in verdict["buckets"]:
        lines.append(
            f"| `{b['key']}` | {b['hr_baseline']:.3f} | {b['hr_candidate']:.3f} | "
            f"{b['delta_pp']:+.3f} | {b['n_events']} | "
            f"{'yes' if b['uplift_ok'] else 'no'} | "
            f"{'yes' if b['events_ok'] else 'no'} |"
        )
    return "\n".join(lines)


def render_adr_body(verdict: dict[str, Any]) -> str:
    """Render an ADR-shaped decision/alternatives/consequences/evidence body.

    The output is meant to be piped into ``scripts/append_adr.py``
    (typically via ``--decision``, ``--alternatives-file`` and
    ``--consequences``) so the W13 reject/accept decision lands in
    ``docs/DECISIONS.md`` with the actual gate numbers in-line.

    The body is structured as four ``## <section>`` blocks so callers
    can split on the headers to isolate fields.
    """
    overall = verdict.get("overall", "?")
    gates = verdict.get("gates") or {}
    br = verdict.get("brier") or {}

    g1 = gates.get("G1_uplift", {})
    g2 = gates.get("G2_brier", {})
    g3 = gates.get("G3_min_events", {})

    decision = (
        "Promote 2H 4th HTF trend layer over the 3-TF baseline."
        if overall == "pass"
        else "Reject 2H 4th HTF trend layer; keep the 3-TF baseline."
    )

    failed = [name for name, g in gates.items() if not g.get("passed")]
    if overall == "pass":
        alts_lines = [
            "- *Reject 2H promotion.* Rejected: all three Q4 gates passed.",
            "- *Defer to next 13-week window.* Rejected: no remaining "
            "unknowns once the gates pass.",
        ]
    else:
        alts_lines = [
            "- *Promote 2H layer anyway.* Rejected: would bypass at least "
            f"one failed Q4 gate ({', '.join(failed) or 'none'}).",
            "- *Defer 13 weeks and re-run gates after more data accrues.* "
            "Recommended fallback when only G3 (events) is the blocker.",
            "- *Drop the 2H investigation entirely.* Rejected: addendum "
            "S6 explicitly schedules a single retry window.",
        ]

    consequences = (
        "4th trend layer (2H) becomes part of the runtime stack; calibration "
        "story expands; downstream Pine Trend TF inputs may need a 4th slot."
        if overall == "pass"
        else (
            "Backlog item stays on the 13-week deferral track. The 3-TF "
            "baseline (4H/1D/1W) remains the production stack. "
            "Re-evaluate at the next addendum-S6 window."
        )
    )

    lines: list[str] = []
    lines.append("## Decision")
    lines.append("")
    lines.append(decision)
    lines.append("")
    lines.append("## Alternatives considered")
    lines.append("")
    lines.extend(alts_lines)
    lines.append("")
    lines.append("## Consequences")
    lines.append("")
    lines.append(consequences)
    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    lines.append(f"- overall: `{overall}`")
    lines.append(
        f"- G1 uplift: passed={g1.get('passed')!r}, "
        f"buckets={g1.get('uplift_bucket_count')!r} "
        f"({', '.join(g1.get('uplift_buckets') or []) or 'none'})"
    )
    lines.append(
        f"- G2 Brier: passed={g2.get('passed')!r}, "
        f"regression={g2.get('brier_regression', 0.0):+.4f} "
        f"(baseline={br.get('baseline', 0.0):.4f}, "
        f"candidate={br.get('candidate', 0.0):.4f})"
    )
    lines.append(
        f"- G3 min-events: passed={g3.get('passed')!r}, "
        f"under_threshold={', '.join(g3.get('under_threshold_buckets') or []) or 'none'}"
    )
    return "\n".join(lines)

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
        description="Evaluate Plan 2.8 Q4-gate (addendum §3.2).",
    )
    parser.add_argument("--bundle", type=Path, required=True,
                        help="Input JSON bundle with A/B per-bucket + Brier stats.")
    parser.add_argument("--uplift-min-pp", type=float, default=DEFAULT_UPLIFT_MIN_PP)
    parser.add_argument("--uplift-min-buckets", type=int, default=DEFAULT_UPLIFT_MIN_BUCKETS)
    parser.add_argument("--brier-max-regression", type=float, default=DEFAULT_BRIER_MAX_REGRESSION)
    parser.add_argument("--min-events-per-bucket", type=int, default=DEFAULT_MIN_EVENTS_PER_BUCKET)
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional path to write the verdict JSON.")
    parser.add_argument("--format", choices=("md", "json", "adr"), default="md",
                        help="Stdout format (default: md). 'adr' renders an "
                             "ADR-body skeleton suitable for append_adr.py.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout body; still writes --output if given.")
    args = parser.parse_args(argv)

    try:
        bundle = _load(args.bundle)
        verdict = evaluate_gate(
            bundle,
            uplift_min_pp=args.uplift_min_pp,
            uplift_min_buckets=args.uplift_min_buckets,
            brier_max_regression=args.brier_max_regression,
            min_events_per_bucket=args.min_events_per_bucket,
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(verdict, indent=2) + "\n", args.output)

    if not args.quiet:
        if args.format == "md":
            print(render_markdown(verdict))
        elif args.format == "adr":
            print(render_adr_body(verdict))
        else:
            print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
