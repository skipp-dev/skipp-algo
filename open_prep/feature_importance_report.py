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

logger = logging.getLogger("open_prep.feature_importance_report")

_ET = _ZoneInfo("America/New_York")

FI_REPORT_DIR = Path("artifacts/open_prep/feature_importance")
DEFAULT_MIN_SAMPLES = 30


# ── State classification ─────────────────────────────────────────────


def _classify_status(report: dict[str, Any], min_samples: int) -> str:
    """Map a raw compute_feature_importance() output to a status token."""
    if report.get("error") == "no feature importance data found":
        return "no_data"
    labeled = int(report.get("labeled_samples") or 0)
    if labeled < min_samples:
        return "insufficient_labels"
    return "ok"


# ── Report generation ────────────────────────────────────────────────


def generate_report(
    *,
    lookback_days: int = 30,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Compute the FI report and wrap it with status + metadata."""
    raw = compute_feature_importance(lookback_days=lookback_days)
    status = _classify_status(raw, min_samples)
    now = datetime.now(_ET)
    return {
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
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
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
        record = generate_report(
            lookback_days=args.lookback,
            min_samples=args.min_samples,
        )
    except Exception:
        logger.exception("Feature-importance report generation failed unexpectedly.")
        return 2

    print(
        f"FI report status={record['status']} "
        f"labeled={record['labeled_samples']} "
        f"threshold={record['min_samples_threshold']} "
        f"shortfall={record['shortfall']}"
    )

    if not args.dry_run:
        out_path = write_report(record)
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
