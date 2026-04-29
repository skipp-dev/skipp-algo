"""Continuous feature-importance report generation (ENG-WS4-02).

Realises ticket ``ENG-WS4-02`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``.

Wraps ``open_prep.outcomes.compute_feature_importance`` into a small,
idempotent CLI so the FI report is generated automatically right after
each backfill run, persisted to disk with a stable schema, and so that
**missing label count is reported as a first-class state** instead of
being a silent no-op.

Run-log layout::

    artifacts/open_prep/feature_importance/
        report_<YYYYMMDDTHHMMSS>.json   # one per run
        latest.json                     # pointer to the last report

Each report carries a ``status`` field:

* ``ok``                  — at least ``min_samples`` labeled samples,
                            full report present in ``report``.
* ``insufficient_labels`` — labeled sample count below the threshold.
                            Report records the count + threshold so a
                            workflow / dashboard can surface the gap.
* ``no_data``             — no FI samples directory yet.

Exit codes:

* ``0`` on every recognised state (state IS the value the workflow
  consumes).
* ``2`` on an unexpected internal error.
"""
from __future__ import annotations

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

from open_prep.outcomes import compute_feature_importance
import contextlib

logger = logging.getLogger("open_prep.feature_importance_report")

_ET = _ZoneInfo("America/New_York")

FI_REPORT_DIR = Path("artifacts/open_prep/feature_importance")
DEFAULT_MIN_SAMPLES = 30

# Drift gate: how far a feature's ranking position may shift between
# consecutive `ok` runs before we surface a ``ranking_drift`` warning.
# The gate is deliberately conservative — drift alerts are an advisory
# signal for the auto-tuner (Phase G) and the weekly review, not a
# hard failure. Cell-level positions are 1-based.
DRIFT_POSITION_THRESHOLD = 3
DRIFT_TOP_N = 10


# ── State classification ─────────────────────────────────────────────


def _classify_status(report: dict[str, Any], min_samples: int) -> str:
    """Map a raw compute_feature_importance() output to a status token."""
    if report.get("error") == "no feature importance data found":
        return "no_data"
    labeled = int(report.get("labeled_samples") or 0)
    if labeled < min_samples:
        return "insufficient_labels"
    return "ok"


# ── Ranking drift detection (ENG-WS4-02.drift) ───────────────────────


def _extract_ranking(raw_report: dict[str, Any] | None) -> list[str]:
    """Return the ordered list of feature keys, highest importance first.

    Handles both the new ``ranked_features`` list (if ever introduced)
    and the current ``features`` dict keyed by feature name with an
    ``importance_normalized`` score. Features with no score are
    dropped so the ranking is stable.
    """
    if not raw_report or not isinstance(raw_report, dict):
        return []
    ranked = raw_report.get("ranked_features")
    if isinstance(ranked, list) and ranked:
        return [str(x) for x in ranked]
    feats = raw_report.get("features")
    if not isinstance(feats, dict):
        return []
    items: list[tuple[str, float]] = []
    for key, val in feats.items():
        if not isinstance(val, dict):
            continue
        score = val.get("importance_normalized")
        if score is None:
            score = val.get("mean_separation")
        try:
            items.append((str(key), float(score)))
        except (TypeError, ValueError):
            continue
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in items]


def compute_ranking_drift(
    current: list[str],
    previous: list[str],
    *,
    top_n: int = DRIFT_TOP_N,
    position_threshold: int = DRIFT_POSITION_THRESHOLD,
) -> dict[str, Any]:
    """Compare two feature rankings and return a drift summary.

    Fields:
      * ``status`` — ``ok`` | ``warn`` | ``unknown`` (``unknown`` if no
        previous ranking is available).
      * ``max_position_delta`` — worst absolute position shift within
        the top-``top_n`` features.
      * ``drifted_features`` — list of ``{feature, previous, current,
        delta}`` dicts for features whose shift exceeds
        ``position_threshold``.

    A feature that drops out of the top-``top_n`` entirely is treated
    as a ``top_n + 1`` position to avoid silent top-list churn.
    """
    if not current or not previous:
        return {
            "status": "unknown",
            "max_position_delta": 0,
            "drifted_features": [],
            "position_threshold": int(position_threshold),
            "top_n": int(top_n),
        }

    def _pos(seq: list[str], key: str) -> int:
        try:
            return seq.index(key) + 1
        except ValueError:
            return top_n + 1

    candidates = set(current[:top_n]) | set(previous[:top_n])
    drifted: list[dict[str, Any]] = []
    max_delta = 0
    for feat in sorted(candidates):
        pc = _pos(current, feat)
        pp = _pos(previous, feat)
        delta = pc - pp
        abs_delta = abs(delta)
        if abs_delta > max_delta:
            max_delta = abs_delta
        if abs_delta > position_threshold:
            drifted.append({
                "feature": feat,
                "previous": pp,
                "current": pc,
                "delta": delta,
            })
    drifted.sort(key=lambda d: -abs(int(d["delta"])))
    return {
        "status": "warn" if drifted else "ok",
        "max_position_delta": int(max_delta),
        "drifted_features": drifted,
        "position_threshold": int(position_threshold),
        "top_n": int(top_n),
    }


def _load_previous_latest(report_dir: Path) -> dict[str, Any] | None:
    """Read the previous ``latest.json`` if it exists (pre-overwrite)."""
    latest = report_dir / "latest.json"
    if not latest.exists():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Report generation ────────────────────────────────────────────────


def generate_report(
    *,
    lookback_days: int = 30,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    previous_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the FI report and wrap it with status + metadata.

    When ``previous_report`` is supplied and both it and the current run
    are in ``ok`` state, a ``ranking_drift`` block is attached so the
    workflow / auto-tuner can react to top-feature re-ordering (Q3/Q4
    plan §2.2 E4 — Outcome Backfill Produktionshärtung).
    """
    raw = compute_feature_importance(lookback_days=lookback_days)
    status = _classify_status(raw, min_samples)
    now = datetime.now(_ET)
    record: dict[str, Any] = {
        "run_id": now.strftime("%Y%m%dT%H%M%S"),
        "generated_at_et": now.isoformat(),
        "lookback_days": int(lookback_days),
        "min_samples_threshold": int(min_samples),
        "labeled_samples": int(raw.get("labeled_samples") or 0),
        "total_samples": int(raw.get("total_samples") or 0),
        "status": status,
        "report": raw if status == "ok" else None,
        "shortfall": (
            max(0, int(min_samples) - int(raw.get("labeled_samples") or 0))
            if status == "insufficient_labels"
            else 0
        ),
    }

    # Ranking drift is only meaningful when both sides have a full report.
    prev_status = (previous_report or {}).get("status")
    if status == "ok" and prev_status == "ok":
        current_ranking = _extract_ranking(raw)
        previous_ranking = _extract_ranking((previous_report or {}).get("report"))
        record["ranking_drift"] = compute_ranking_drift(current_ranking, previous_ranking)
    else:
        record["ranking_drift"] = {
            "status": "unknown",
            "max_position_delta": 0,
            "drifted_features": [],
            "position_threshold": DRIFT_POSITION_THRESHOLD,
            "top_n": DRIFT_TOP_N,
            "reason": (
                "no prior ok-report available"
                if prev_status != "ok"
                else "current report not ok"
            ),
        }
    return record


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


def write_report(
    record: dict[str, Any],
    *,
    report_dir: Path | None = None,
) -> Path:
    target_dir = report_dir if report_dir is not None else FI_REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"report_{record['run_id']}.json"
    _atomic_write_json(out_path, record)
    _atomic_write_json(target_dir / "latest.json", record)
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the recurring feature-importance report (ENG-WS4-02).",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=30,
        help="Lookback window in days for FI samples (default: 30).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"Minimum labeled samples required for a full report (default: {DEFAULT_MIN_SAMPLES}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the report without writing to disk.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    try:
        previous_record = _load_previous_latest(FI_REPORT_DIR)
        record = generate_report(
            lookback_days=args.lookback,
            min_samples=args.min_samples,
            previous_report=previous_record,
        )
    except Exception:
        logger.exception("Feature-importance report generation failed unexpectedly.")
        return 2

    drift = record.get("ranking_drift") or {}
    drift_status = drift.get("status", "unknown")
    drift_max = drift.get("max_position_delta", 0)
    print(
        f"FI report status={record['status']} "
        f"labeled={record['labeled_samples']} "
        f"threshold={record['min_samples_threshold']} "
        f"shortfall={record['shortfall']} "
        f"drift_status={drift_status} "
        f"drift_max_delta={drift_max}"
    )
    if drift_status == "warn":
        print("⚠ Feature-importance ranking drift detected:")
        for d in drift.get("drifted_features", []):
            feat = d.get("feature")
            delta = d.get("delta", 0)
            sign = "+" if int(delta) >= 0 else ""
            print(
                f"  {feat}: position {d.get('previous')} → {d.get('current')} "
                f"({sign}{delta})"
            )

    if not args.dry_run:
        out_path = write_report(record)
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
