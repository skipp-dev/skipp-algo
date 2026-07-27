"""§G3 bridge: ab_arms paired records × outcome labels → watchdog comparison.

`open_prep.ab_arms` accumulates one paired arm-A/arm-B record per trading day
in ``artifacts/open_prep/ab_arms/`` (PR #4108), and
``open_prep.outcome_backfill --ab-arm-labels`` resolves 30-minute
mark-to-market labels for every symbol either arm ranked into
``labels_<day>.json`` next to them. This bridge is the third, previously
missing edge of the chain: it folds those labeled days into ONE cumulative
``ab_comparison.json`` that ``scripts.g23_ab_watchdog --input`` appends to
``docs/ab/g23_history.jsonl`` — the sample the §G2 rollback / §G3 promotion
gates actually read. Before it existed the history sat empty
("awaiting_first_run") while the records accumulated unread.

Cumulative by contract (W3-2)
-----------------------------
The watchdog runs SPRT on the **latest** history entry alone, expecting its
(n, k) to already span the full corpus — summing per-day entries would
double-count. So this bridge always aggregates EVERY labeled day and the
watchdog appends one cumulative snapshot per run.

Honesty rules
-------------
* Only symbols with a resolved ``profitable_30m`` count; the unlabeled
  remainder is disclosed in ``coverage``, never silently dropped.
* Days with ``status != "ok"`` (arm_b_unavailable / error) contribute nothing
  and are counted in ``coverage.days_skipped_not_ok``.
* Zero treatment observations → NO output file (exit 0). The watchdog then
  keeps reporting awaiting_first_run, which is the truthful state.

Exit codes: 0 (comparison written, or honestly nothing to compare),
2 (unexpected error).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("scripts.g3_bridge_ab_arms")

DEFAULT_AB_DIR = Path("artifacts/open_prep/ab_arms")
EXPERIMENT_NAME = "g3-arm-b-candidate-weights"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Unreadable %s: %s", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _resolved_hits(
    symbols: list[str], labels: dict[str, Any],
) -> tuple[int, int, int]:
    """Return ``(n, k, unlabeled)`` for *symbols* under *labels*."""
    n = k = unlabeled = 0
    for symbol in symbols:
        entry = labels.get(symbol)
        outcome = entry.get("profitable_30m") if isinstance(entry, dict) else None
        if outcome is None:
            unlabeled += 1
            continue
        n += 1
        if bool(outcome):
            k += 1
    return n, k, unlabeled


def build_cumulative_comparison(
    *, ab_dir: Path = DEFAULT_AB_DIR,
) -> dict[str, Any] | None:
    """Aggregate every labeled ok-day into one watchdog-compatible comparison.

    Returns ``None`` when there is not a single resolved treatment
    observation — the caller must then write nothing.
    """
    control_n = control_k = treatment_n = treatment_k = 0
    control_unlabeled = treatment_unlabeled = 0
    days_aggregated = 0
    days_skipped_not_ok = 0
    days_awaiting_labels = 0
    day_span: list[str] = []

    for record_path in sorted(ab_dir.glob("ab_arms_*.json")):
        record = _load_json(record_path)
        if record is None:
            continue
        if record.get("status") != "ok":
            days_skipped_not_ok += 1
            continue
        day = str(record.get("day") or record_path.stem.removeprefix("ab_arms_"))
        labels_payload = _load_json(ab_dir / f"labels_{day}.json")
        if labels_payload is None:
            days_awaiting_labels += 1
            continue
        labels = labels_payload.get("labels")
        if not isinstance(labels, dict):
            days_awaiting_labels += 1
            continue

        arm_a = [s for s in record.get("arm_a_top") or [] if isinstance(s, str)]
        arm_b = [s for s in record.get("arm_b_top") or [] if isinstance(s, str)]
        a_n, a_k, a_miss = _resolved_hits(arm_a, labels)
        b_n, b_k, b_miss = _resolved_hits(arm_b, labels)
        control_n += a_n
        control_k += a_k
        control_unlabeled += a_miss
        treatment_n += b_n
        treatment_k += b_k
        treatment_unlabeled += b_miss
        days_aggregated += 1
        day_span.append(day)

    if treatment_n <= 0:
        logger.info(
            "No resolved treatment observations yet (%d day(s) aggregated, "
            "%d awaiting labels, %d not ok) — no comparison emitted.",
            days_aggregated, days_awaiting_labels, days_skipped_not_ok,
        )
        return None

    return {
        "experiment": EXPERIMENT_NAME,
        # The block g23_ab_watchdog._extract_arm_totals/_make_history_entry read.
        "sprt": {
            "n": treatment_n,
            "k": treatment_k,
            "hit_rate": round(treatment_k / treatment_n, 4),
            "control_n": control_n,
            "control_hit_rate": (
                round(control_k / control_n, 4) if control_n else None
            ),
        },
        "days_aggregated": days_aggregated,
        "day_first": day_span[0],
        "day_last": day_span[-1],
        "coverage": {
            "control_unlabeled": control_unlabeled,
            "treatment_unlabeled": treatment_unlabeled,
            "days_awaiting_labels": days_awaiting_labels,
            "days_skipped_not_ok": days_skipped_not_ok,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ab-dir", type=Path, default=DEFAULT_AB_DIR)
    parser.add_argument(
        "--out", type=Path, required=True,
        help="Where to write ab_comparison.json (omitted entirely when there "
             "is nothing to compare yet).",
    )
    args = parser.parse_args(argv)

    try:
        comparison = build_cumulative_comparison(ab_dir=args.ab_dir)
        if comparison is None:
            return 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        sprt = comparison["sprt"]
        logger.info(
            "Wrote %s: treatment %d/%d vs control hit_rate=%s over %d day(s).",
            args.out, sprt["k"], sprt["n"], sprt["control_hit_rate"],
            comparison["days_aggregated"],
        )
        return 0
    except Exception:
        logger.exception("g3 bridge failed")
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
