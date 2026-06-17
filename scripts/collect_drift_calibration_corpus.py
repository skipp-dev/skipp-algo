"""W9-7 / issue #2798 — Drift-threshold calibration corpus collector.

Reads a ``compute_live_drift`` output JSON (schema 1.3.0) and appends one
JSONL row per variant to the long-running calibration corpus at

    artifacts/drift/calibration_corpus.jsonl

Each row captures the fields needed for a future ROC analysis that will
replace the placeholder ``_VERDICT_BANDS`` in ``compute_live_drift.py``
with statistically calibrated thresholds (see GitHub issue #2798).

Schema per row
--------------
::

    {
      "collected_at": "2026-06-16T07:18:00+00:00",  # wall-clock of this run
      "computed_at":  "2026-06-16T07:15:42+00:00",  # from drift JSON header
      "live_window_days": 90,                        # from drift JSON header
      "variant": "smc_breaker_btc",
      "n_live_trades": 24,
      "live_sharpe": 0.71,
      "backtest_sharpe": 0.93,
      "drift_score": 0.76,
      "verdict": "acceptable",
      "slippage_ks_p": 0.32,
      "hr_in_bootstrap_ci": true,
      "overperformance_capped": false,
      "trades_per_year_live": 97.3,
      "trades_per_year_backtest": 142.1,
      "slippage_ks_reference_type": "backtest_samples",
      "human_label": null
    }

``human_label`` is ``null`` until a human retrospectively annotates the
row with the true outcome:

* ``"drift"``    — live performance was degraded in a way that mattered
* ``"no_drift"`` — live performance was acceptable in hindsight

Once enough labelled rows are available (≥3 months, ≥2 families —
see issue #2798), run the companion ``scripts/calibrate_drift_thresholds.py``
(to be written in Q3 2026) to derive principled ``_VERDICT_BANDS`` values.

Usage
-----
::

    python -m scripts.collect_drift_calibration_corpus \\
        --drift-json  cache/live/drift_2026-06-16.json \\
        --corpus      artifacts/drift/calibration_corpus.jsonl

    # dry-run (print rows to stdout, do not write):
    python -m scripts.collect_drift_calibration_corpus \\
        --drift-json  cache/live/drift_2026-06-16.json \\
        --dry-run
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Corpus row builder
# ---------------------------------------------------------------------------

def _build_rows(
    drift_payload: dict[str, Any],
    collected_at: str,
) -> list[dict[str, Any]]:
    """Return one corpus row per variant in *drift_payload*."""
    computed_at = drift_payload.get("computed_at", "")
    live_window_days = drift_payload.get("live_window_days")
    variants = drift_payload.get("variants", [])

    rows: list[dict[str, Any]] = []
    for v in variants:
        rows.append(
            {
                "collected_at": collected_at,
                "computed_at": computed_at,
                "live_window_days": live_window_days,
                "variant": v.get("variant", ""),
                "n_live_trades": v.get("n_live_trades", None),
                "live_sharpe": v.get("live_sharpe", None),
                "backtest_sharpe": v.get("backtest_sharpe", None),
                "drift_score": v.get("drift_score", None),
                "verdict": v.get("verdict", ""),
                "slippage_ks_p": v.get("slippage_ks_p", None),
                "hr_in_bootstrap_ci": v.get("hr_in_bootstrap_ci", None),
                "overperformance_capped": v.get("overperformance_capped", False),
                "trades_per_year_live": v.get("trades_per_year_live", None),
                "trades_per_year_backtest": v.get("trades_per_year_backtest", None),
                "slippage_ks_reference_type": v.get(
                    "slippage_ks_reference",  # legacy field name in JSON
                    v.get("slippage_ks_reference_type", "unavailable"),
                ),
                # Retrospective label — filled in by a human after the fact.
                # Allowed values once labelled: "drift" | "no_drift".
                "human_label": None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Duplicate guard
# ---------------------------------------------------------------------------

def _existing_keys(corpus_path: Path) -> set[tuple[str, str]]:
    """Return (computed_at, variant) pairs already in the corpus."""
    keys: set[tuple[str, str]] = set()
    if not corpus_path.exists():
        return keys
    with corpus_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                import warnings
                warnings.warn(f"Corrupt JSONL line in {corpus_path} (skipped for dedup): {exc}", stacklevel=2)
                continue
            key = (str(row.get("computed_at", "")), str(row.get("variant", "")))
            keys.add(key)
    return keys


# ---------------------------------------------------------------------------
# Idempotent append (deduplicates on computed_at × variant)
# ---------------------------------------------------------------------------

def _append_rows(corpus_path: Path, rows: list[dict[str, Any]]) -> int:
    """Append *rows* to *corpus_path*; create parent dirs as needed.

    Returns the number of rows actually written (0 if all were duplicates).
    """
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_keys(corpus_path)
    written = 0
    with corpus_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            key = (str(row.get("computed_at", "")), str(row.get("variant", "")))
            if key in existing:
                continue
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            existing.add(key)
            written += 1
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append drift snapshot rows to the calibration corpus."
    )
    parser.add_argument(
        "--drift-json",
        required=True,
        metavar="PATH",
        help="Path to a compute_live_drift output JSON file.",
    )
    parser.add_argument(
        "--corpus",
        default="artifacts/drift/calibration_corpus.jsonl",
        metavar="PATH",
        help=(
            "Destination JSONL corpus file "
            "(default: artifacts/drift/calibration_corpus.jsonl)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rows to stdout without writing to the corpus.",
    )
    args = parser.parse_args(argv)

    drift_path = Path(args.drift_json)
    try:
        drift_payload: dict[str, Any] = json.loads(
            drift_path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        print(f"error: cannot read --drift-json: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in --drift-json: {exc}", file=sys.stderr)
        return 1

    if not isinstance(drift_payload, dict):
        print("error: drift JSON root must be an object, not a list or scalar", file=sys.stderr)
        return 1

    # Validate required top-level fields before building rows.
    if not isinstance(drift_payload.get("computed_at"), str) or not drift_payload["computed_at"]:
        print("error: drift JSON missing or empty 'computed_at'", file=sys.stderr)
        return 1
    if not isinstance(drift_payload.get("live_window_days"), int):
        print("error: drift JSON missing or non-integer 'live_window_days'", file=sys.stderr)
        return 1
    if not isinstance(drift_payload.get("variants"), list):
        print("error: drift JSON 'variants' must be a list", file=sys.stderr)
        return 1

    # Validate that each variant entry has a non-empty 'variant' key so that
    # dedup and ROC analysis can reliably group by variant name.
    bad_variants = [
        i for i, v in enumerate(drift_payload["variants"])
        if not isinstance(v, dict) or not v.get("variant")
    ]
    if bad_variants:
        print(
            f"error: drift JSON variants at indices {bad_variants} are missing or"
            " have an empty 'variant' field.",
            file=sys.stderr,
        )
        return 1

    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    rows = _build_rows(drift_payload, collected_at)

    if not rows:
        print("warning: no variant rows found in drift JSON.", file=sys.stderr)
        return 0

    if args.dry_run:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0

    written = _append_rows(Path(args.corpus), rows)
    skipped = len(rows) - written
    print(
        f"corpus: wrote {written} row(s), skipped {skipped} duplicate(s) "
        f"→ {args.corpus}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (SIGINT/KeyboardInterrupt).")
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error in %s", __name__, exc_info=True)
        raise SystemExit(1) from None
