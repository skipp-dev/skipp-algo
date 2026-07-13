"""Reaction-zone shadow study — is the level-reclaim a better follow-through
predictor than the old (inverted) rejection band?

Reads the measurement event ledgers (``events_*.jsonl``), pulls the SWEEP-family
events that carry the ``reaction_schema_version`` shadow features (emitted by
``smc_integration.measurement_evidence`` when ``ENABLE_REACTION_ZONE_STUDY=1``), and
compares three boolean confirmation variants as predictors of the DISJOINT
follow-through outcome ``reaction_outcome_late``:

* ``old_band``     — the EARLY-rejection cohort: a band close BEFORE any reclaim
  (ordering via ``bars_to_*``; the raw flag alone would also match a band close
  AFTER a reclaim, and the sweep bar itself already closed through the level, so
  a band close is a fall back below/above it, not a partial recovery).
* ``level_cross``  — ``reaction_level_reclaimed`` (the corrected authoritative
  reclaim: a close back through the level in the reversal direction, unbounded).
* ``mirrored_band``— reclaimed AND within a narrow band just past the level
  (``0 <= reaction_close_distance_pct <= reaction_band_width_pct``).

Leakage note: the confirmation is measured on bars 1..N of the sweep lookahead and
``reaction_outcome_late`` on the DISJOINT window (bars N+1..lookahead), so a
confirmation is never a component of its own label. The study evaluates whether
early confirmation *predicts* later follow-through, split by bull/bear.

For each (variant, direction) it reports the confusion split — base rate,
P(outcome | confirmed), P(outcome | not confirmed) and their difference (``lift``)
— plus a per-direction ``best_variant`` and a promotion verdict gated on sample
size (total AND ``MIN_CELL_SAMPLES`` in BOTH confusion cells) and a positive lift.
This is OBSERVE-ONLY: nothing here changes any score.

Statistical caveat (why ``PROMOTABLE`` is a *candidate*, not a validated pick):
``best_variant`` is the max observed lift over six parallel comparisons (3 variants
x 2 directions) with NO multiple-testing correction and no separate
selection/validation split, and ``lift`` carries no confidence interval. A
``PROMOTABLE`` here means "worth a powered follow-up" — the FDR/family-wise
correction and an out-of-sample confirmation fold are deliberately downstream.
Records whose disjoint late window has not resolved to a real boolean
``reaction_outcome_late`` are dropped as not-yet-gradeable (never counted as a miss).

Exit codes: 0 = wrote/updated the snapshot; 5 = no reaction samples yet (appends
nothing); 1 = usage/read error. The ledger read fails CLOSED on corruption.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json
from smc_core.event_ledger import ledger_label

DEFAULT_SNAPSHOT = "artifacts/monitoring/reaction_zone_shadow.json"
MIN_SAMPLES = 40
# Floor on BOTH confusion cells (confirmed / not-confirmed) before a PROMOTABLE
# verdict. Without it a lopsided split (e.g. 1 confirmed vs 39 not) lets a single
# event set p_outcome_if_confirmed to 0/1 and manufacture a large, meaningless lift.
MIN_CELL_SAMPLES = 10
LIFT_PROMOTE_THRESHOLD = 0.05
VARIANTS = ("old_band", "level_cross", "mirrored_band")
DIRECTIONS = ("bull", "bear")
VERDICT_CODE = {"INCONCLUSIVE": 0, "SHADOW": 1, "PROMOTABLE": 2}


# ── variant derivation ───────────────────────────────────────────────────────
def derive_variants(feats: dict[str, Any]) -> dict[str, bool] | None:
    """Return the three boolean confirmation variants, or ``None`` if malformed."""
    try:
        reclaimed = bool(feats["reaction_level_reclaimed"])
        in_band = bool(feats["reaction_in_rejection_band"])
        dist = float(feats["reaction_close_distance_pct"])
        width = float(feats["reaction_band_width_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    # bars_to_* order ONLY the old_band cohort, so a missing OR corrupt value
    # must fail-closed on old_band alone (default -1 → the flags-guard drops the
    # sample from that cohort), never discard the still-valid level_cross /
    # mirrored_band variants — keeping the two failure modes symmetric.
    try:
        bars_to_band = int(feats.get("reaction_bars_to_rejection_band", -1))
        bars_to_reclaim = int(feats.get("reaction_bars_to_reclaim", -1))
    except (TypeError, ValueError):
        bars_to_band = bars_to_reclaim = -1
    mirrored = reclaimed and (0.0 <= dist <= width)
    # ``old_band`` is the EARLY-rejection cohort: at the time the band close fired
    # no reclaim had happened yet. The producer keeps scanning after a reclaim, so
    # both raw flags can be True with the band close AFTER the reclaim — that
    # sample is a reclaim, not an early rejection, and must not contaminate the
    # cohort. Ordering via bars_to_* (1-indexed; guarded by the flags).
    early_band = in_band and (not reclaimed or (bars_to_band >= 1 and bars_to_band < bars_to_reclaim))
    return {"old_band": early_band, "level_cross": reclaimed, "mirrored_band": mirrored}


def collect_samples(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, bool], int]]:
    """Return ``(direction, variants, outcome)`` for reaction-tagged SWEEP events."""
    out: list[tuple[str, dict[str, bool], int]] = []
    for ev in events:
        if str(ev.get("family", "")).upper() != "SWEEP":
            continue
        feats = ev.get("features") or {}
        # Era-cut: schema v2 (edge-censoring fix) guarantees the late label was
        # observed on the FULL disjoint outcome window; v1 rows may be right-censored.
        try:
            if int(feats.get("reaction_schema_version", 0)) < 2:
                continue
        except (TypeError, ValueError):
            continue
        direction = str(feats.get("reaction_direction", "")).lower()
        if direction not in DIRECTIONS:
            continue
        variants = derive_variants(feats)
        if variants is None:
            continue
        # reaction_outcome_late is a LABEL (schema 1.1 -> outcome_extras, 1.0 -> features);
        # ledger_label reads either. An unresolved/malformed late window is not a genuine
        # bool -> drop it so it can never be a silent miss.
        late = ledger_label(ev, "reaction_outcome_late")
        if not isinstance(late, bool):
            continue
        out.append((direction, variants, 1 if late else 0))
    return out


# ── statistics ───────────────────────────────────────────────────────────────
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def evaluate_variant(pairs: list[tuple[bool, int]]) -> dict[str, Any]:
    """2x2 confusion metrics for one (variant, direction): confirmed vs outcome."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "n_confirmed": 0, "base_rate": None,
                "p_outcome_if_confirmed": None, "p_outcome_if_not": None, "lift": None}
    outcomes = [o for _, o in pairs]
    confirmed = [o for c, o in pairs if c]
    not_confirmed = [o for c, o in pairs if not c]
    p_conf = _mean([float(o) for o in confirmed]) if confirmed else None
    p_not = _mean([float(o) for o in not_confirmed]) if not_confirmed else None
    lift = (p_conf - p_not) if (p_conf is not None and p_not is not None) else None
    return {
        "n": n,
        "n_confirmed": len(confirmed),
        "base_rate": round(_mean([float(o) for o in outcomes]), 6),
        "p_outcome_if_confirmed": None if p_conf is None else round(p_conf, 6),
        "p_outcome_if_not": None if p_not is None else round(p_not, 6),
        "lift": None if lift is None else round(lift, 6),
    }


def _verdict(n: int, n_confirmed: int, n_not_confirmed: int, lift: float | None) -> str:
    if n < MIN_SAMPLES:
        return "INCONCLUSIVE"
    # A positive lift promotes only when BOTH confusion cells clear the floor;
    # otherwise a single-sample cell can fabricate the effect (MIN_CELL_SAMPLES).
    if (
        lift is not None
        and lift > LIFT_PROMOTE_THRESHOLD
        and n_confirmed >= MIN_CELL_SAMPLES
        and n_not_confirmed >= MIN_CELL_SAMPLES
    ):
        return "PROMOTABLE"
    return "SHADOW"


def evaluate(events: list[dict[str, Any]]) -> dict[str, Any]:
    samples = collect_samples(events)
    result: dict[str, Any] = {"n_reaction_samples": len(samples), "by_direction": {}}
    for direction in DIRECTIONS:
        dir_samples = [(v, o) for d, v, o in samples if d == direction]
        variants_out: dict[str, Any] = {}
        for variant in VARIANTS:
            pairs = [(v[variant], o) for v, o in dir_samples]
            metrics = evaluate_variant(pairs)
            metrics["verdict"] = _verdict(
                metrics["n"], metrics["n_confirmed"],
                metrics["n"] - metrics["n_confirmed"], metrics["lift"],
            )
            variants_out[variant] = metrics
        # Best variant = highest lift among those with a defined lift.
        ranked = [(k, m["lift"]) for k, m in variants_out.items() if m["lift"] is not None]
        best = max(ranked, key=lambda kv: kv[1])[0] if ranked else None
        result["by_direction"][direction] = {
            "n": len(dir_samples), "best_variant": best, "variants": variants_out,
        }
    return result


# ── event reading (fail-closed) ──────────────────────────────────────────────
def _read_events_from_dir(benchmark_dir: Path) -> list[dict[str, Any]]:
    from smc_core.event_ledger import read_event_ledger

    events: list[dict[str, Any]] = []
    # strict=True: a malformed / off-schema line raises EventLedgerSchemaError,
    # which main()'s fail-closed handler turns into a refusal — a promotion
    # verdict is never computed from a partial or corrupt corpus.
    for path in sorted(glob.glob(str(benchmark_dir / "*" / "*" / "events_*.jsonl"))):
        events.extend(read_event_ledger(Path(path), strict=True))
    return events


def _read_events_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON list of events")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reaction-zone shadow follow-through study.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--benchmark-dir", type=Path, help="dir containing */*/events_*.jsonl")
    src.add_argument("--events-json", type=Path, help="a JSON list of event dicts")
    parser.add_argument("--snapshot", type=Path, default=Path(DEFAULT_SNAPSHOT))
    parser.add_argument("--now-iso", type=str, default="", help="timestamp stamped into the snapshot")
    args = parser.parse_args(argv)

    try:
        events = (
            _read_events_from_dir(args.benchmark_dir)
            if args.benchmark_dir is not None
            else _read_events_from_json(args.events_json)
        )
    except Exception as exc:  # fail-closed: a corrupt ledger must not fabricate a verdict
        print(f"ERROR: reaction-zone shadow read failed: {exc}", file=sys.stderr)
        return 1

    result = evaluate(events)
    if result["n_reaction_samples"] == 0:
        print("No reaction-zone samples in the ledger yet (nothing written).", file=sys.stderr)
        return 5

    result["updated_at"] = args.now_iso or None
    result["config"] = {"min_samples": MIN_SAMPLES, "lift_promote_threshold": LIFT_PROMOTE_THRESHOLD}
    atomic_write_json(result, args.snapshot, indent=2, sort_keys=False)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
