"""Candidate weight-set production with drift-gate (ENG-WS4-03).

Realises ticket ``ENG-WS4-03`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``.

The pieces — feature-importance computation
(:mod:`open_prep.outcomes`.compute_feature_importance), Bayesian weight
adjustment (compute_weight_adjustments), drift detection
(check_scorer_drift), and weight persistence
(:mod:`open_prep.scorer`.save_weight_set) — already exist. This module
wires them into one deterministic CLI so a candidate weight set can be
produced automatically, gated against extreme drift, and versioned
distinctly from the default weights.

Run-log layout::

    artifacts/open_prep/candidate_weights/
        candidate_<run_id>.json   # full record per run
        latest.json               # pointer to the last record

Status values:

* ``ok``                — weights regenerated, drift gate clean, saved
                          as ``weights_candidate.json`` via scorer.
* ``insufficient_data`` — FI report below threshold, no candidate
                          produced; default keeps serving.
* ``drift_blocked``     — weights computed but drift-gate fired; the
                          candidate file is *not* written so the next
                          loader call still resolves to default.
* ``error``             — unexpected failure; details captured.

Exit codes:

* ``0`` for ok / insufficient_data / drift_blocked (state is the
  product output).
* ``2`` only on internal error.
"""
from __future__ import annotations

import contextlib
import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

from open_prep.outcomes import (
    check_scorer_drift,
    compute_feature_importance,
    compute_weight_adjustments,
    scorer_update_to_json,
)
from open_prep.scorer import DEFAULT_WEIGHTS, save_weight_set

logger = logging.getLogger("open_prep.candidate_weights")

_ET = _ZoneInfo("America/New_York")

CANDIDATE_RUN_LOG_DIR = Path("artifacts/open_prep/candidate_weights")
CANDIDATE_LABEL = "candidate"
DEFAULT_MIN_SAMPLES = 30
DEFAULT_MAX_DRIFT = 0.50


# ── Generation ────────────────────────────────────────────────────────


def _now_run_id() -> tuple[str, str]:
    now = datetime.now(_ET)
    return now.strftime("%Y%m%dT%H%M%S"), now.isoformat()


def generate_candidate(
    *,
    lookback_days: int = 30,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_drift: float = DEFAULT_MAX_DRIFT,
) -> dict[str, Any]:
    """Compute a candidate weight set, gated against drift.

    Returns a serialisable record with status + payload; never raises
    for known states (insufficient data, drift block).
    """
    run_id, started_at = _now_run_id()
    base: dict[str, Any] = {
        "run_id": run_id,
        "generated_at_et": started_at,
        "lookback_days": int(lookback_days),
        "min_samples_threshold": int(min_samples),
        "max_drift_threshold": float(max_drift),
    }

    fi_report = compute_feature_importance(lookback_days=lookback_days)
    labeled = int(fi_report.get("labeled_samples") or 0)

    if "error" in fi_report or labeled < min_samples:
        return {
            **base,
            "status": "insufficient_data",
            "labeled_samples": labeled,
            "shortfall": max(0, int(min_samples) - labeled),
            "candidate_label": None,
            "drift_violations": [],
            "weights": None,
            "fi_error": fi_report.get("error"),
        }

    update = compute_weight_adjustments(fi_report, current_weights=dict(DEFAULT_WEIGHTS))
    candidate = update.updated_weights
    violations = check_scorer_drift(candidate, max_drift=max_drift)

    if violations:
        return {
            **base,
            "status": "drift_blocked",
            "labeled_samples": labeled,
            "shortfall": 0,
            "candidate_label": None,
            "drift_violations": violations,
            "weights": candidate,
            "weight_update": scorer_update_to_json(update),
        }

    return {
        **base,
        "status": "ok",
        "labeled_samples": labeled,
        "shortfall": 0,
        "candidate_label": CANDIDATE_LABEL,
        "drift_violations": [],
        "weights": candidate,
        "weight_update": scorer_update_to_json(update),
    }


# ── Persistence ──────────────────────────────────────────────────────


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_run_log(
    record: dict[str, Any],
    *,
    log_dir: Path | None = None,
) -> Path:
    target_dir = log_dir if log_dir is not None else CANDIDATE_RUN_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"candidate_{record['run_id']}.json"
    _atomic_write_json(out_path, record)
    _atomic_write_json(target_dir / "latest.json", record)
    return out_path


def persist_candidate(record: dict[str, Any]) -> bool:
    """Save the candidate weight set to disk if status==ok.

    Returns True if a candidate file was written, False otherwise. The
    drift gate (status=='drift_blocked') is the explicit reason this
    function refuses to write — DoD: 'Drift-Gate blockiert extreme
    Spruenge'.
    """
    if record.get("status") != "ok":
        return False
    weights = record.get("weights")
    if not isinstance(weights, dict):
        return False
    save_weight_set(CANDIDATE_LABEL, weights)
    return True


# ── CLI ──────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Produce candidate scorer weights with drift-gate (ENG-WS4-03).",
    )
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--max-drift", type=float, default=DEFAULT_MAX_DRIFT)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute the record without writing to disk.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    try:
        record = generate_candidate(
            lookback_days=args.lookback,
            min_samples=args.min_samples,
            max_drift=args.max_drift,
        )
    except Exception:
        logger.exception("Candidate weight generation failed unexpectedly.")
        return 2

    print(
        f"Candidate weights status={record['status']} "
        f"labeled={record['labeled_samples']} "
        f"violations={len(record.get('drift_violations') or [])}"
    )

    if not args.dry_run:
        log_path = write_run_log(record)
        print(f"Run log: {log_path}")
        if persist_candidate(record):
            print(f"Saved candidate weight set as label={CANDIDATE_LABEL!r}")
        elif record.get("status") == "drift_blocked":
            print("Candidate NOT saved — drift gate blocked the update.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
