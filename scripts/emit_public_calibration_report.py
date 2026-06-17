"""Emit the daily public calibration report (Q3/Q4 plan §3.1.1).

This is the SHA-verifiable, redacted-for-public-consumption snapshot that
backs the GitHub-Pages dashboard at ``docs/calibration/index.html``.

Inputs (best-effort, all optional):
* ``--input-cal PATH`` — a ``zone_priority_calibration.json`` (or
  ``zone_priority_contextual_calibration.json``) artifact emitted by
  the rolling benchmark. When omitted, the latest matching artifact
  under ``artifacts/reports/`` is used; if none is present, the
  emitted report carries ``status: "awaiting_first_run"`` rather
  than failing — so the workflow stays green on a clean checkout.
* ``--history PATH`` — alternate history JSONL location. Defaults to
  the sibling of the calibration source (matching
  :func:`scripts.smc_zone_priority_calibration.append_history_entry`).
* ``--output PATH`` — where to write the public artifact. Defaults to
  ``docs/calibration/calibration_report_public.json``.

Outputs:
* The public JSON, with the schema documented in :data:`PUBLIC_SCHEMA_VERSION`.
* A sibling ``calibration_report_public_history.jsonl`` capped at
  ``HISTORY_RETENTION`` entries so the dashboard sparkline stays bounded.

The public artifact is intentionally a **subset** of the internal
calibration artifact: per-symbol breakdowns, raw event counts per
context, and benchmark-source paths are stripped. What remains is the
calibration evidence a reviewer needs to verify the headline claims:

* Corpus size (``n_events``)
* Family weights (``family_weights``)
* Calibration metrics (``ece``, ``smooth_ece``, ``brier``)
* Weighted hit rate (``weighted_hit_rate``)
* Source identifier (``source_commit_sha``, ``source_workflow_run``)
* Schema version + emission timestamp.

The trailing history JSONL feeds the dashboard's ECE / Brier / HR
sparkline.

Exit codes:
* 0 — public artifact written (even if input was missing)
* 1 — fatal error (cannot write output, malformed --input-cal JSON)

Usage::

    python -m scripts.emit_public_calibration_report
    python -m scripts.emit_public_calibration_report \\
        --input-cal artifacts/reports/zone_priority_calibration.json
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

PUBLIC_SCHEMA_VERSION = "1.3.0"
HISTORY_RETENTION = 90  # ~3 months at one entry per day
DEFAULT_OUTPUT = Path("docs/calibration/calibration_report_public.json")
DEFAULT_HISTORY_FILENAME = "calibration_report_public_history.jsonl"
DEFAULT_SEARCH_DIR = Path("artifacts/reports")
_CAL_FILENAME_CANDIDATES = (
    "zone_priority_contextual_calibration.json",
    "zone_priority_calibration.json",
)


def _find_latest_calibration_artifact(search_dir: Path) -> Path | None:
    """Return the most recently modified known calibration artifact.

    Prefers the contextual variant (richer schema). Returns ``None``
    when neither is present so the caller can emit an
    ``awaiting_first_run`` report instead of failing.
    """
    if not search_dir.is_dir():
        return None
    candidates: list[Path] = []
    for name in _CAL_FILENAME_CANDIDATES:
        candidates.extend(search_dir.rglob(name))
    if not candidates:
        return None
    # MTIME-RESOLVER-EXEMPT: candidates are fixed-name files in different
    # subdirs (zone_priority_calibration.json, zone_priority_contextual_calibration.json);
    # filenames carry no timestamp, so mtime is the intended freshness signal.
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _coerce_float(val: Any) -> float | None:
    """Best-effort float coercion that drops None / NaN / non-numeric."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _extract_weighted_hit_rate(payload: dict[str, Any]) -> float | None:
    """Pull the corpus-level weighted hit rate from ``family_stats`` (if any).

    Mirrors :func:`scripts.smc_zone_priority_calibration.append_history_entry`
    so the headline figure on the dashboard matches the trend feed.
    """
    family_stats = payload.get("family_stats") or {}
    total_events = 0
    total_hits = 0
    for fam_stats in family_stats.values():
        if not isinstance(fam_stats, dict):
            continue
        try:
            n = int(fam_stats.get("total_events") or 0)
            h = int(fam_stats.get("total_hits") or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            total_events += n
            total_hits += h
    if total_events <= 0:
        return None
    return round(total_hits / total_events, 6)


def _extract_calibration_metrics(payload: dict[str, Any]) -> dict[str, float]:
    """Pull ECE / smECE / Brier / dCE from the testable_calibration block."""
    testable = payload.get("testable_calibration") or {}
    metrics: dict[str, float] = {}
    for src_key, dest_key in (
        ("ece_binned_n10", "ece"),
        ("smooth_ece", "smooth_ece"),
        ("dce_upper_bound", "dce"),
        ("brier", "brier"),
        ("positive_rate", "positive_rate"),
    ):
        v = _coerce_float(testable.get(src_key))
        if v is not None:
            metrics[dest_key] = round(v, 6)
    # Fall back to top-level brier / ece if present (older artifacts).
    for src_key, dest_key in (("brier_score", "brier"), ("ece", "ece")):
        if dest_key not in metrics:
            v = _coerce_float(payload.get(src_key))
            if v is not None:
                metrics[dest_key] = round(v, 6)
    return metrics


def _extract_n_events(payload: dict[str, Any]) -> int | None:
    """Prefer ``testable_calibration.n_events``; fall back to family-stats sum."""
    testable = payload.get("testable_calibration") or {}
    try:
        n = int(testable.get("n_events") or 0)
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    family_stats = payload.get("family_stats") or {}
    total = 0
    for fam_stats in family_stats.values():
        if not isinstance(fam_stats, dict):
            continue
        try:
            total += int(fam_stats.get("total_events") or 0)
        except (TypeError, ValueError):
            continue
    return total or None


# Field-set required by ``scripts/check_c12_trigger.py`` so the public
# report emits a producer-side schema the trigger consumer can validate.
# Keeping this constant local (single-source-of-truth lives in the
# trigger consumer; mirroring it here would invite drift). The trigger
# pins MIN_LIVE_DAYS / MIN_LIVE_TRADES / acceptable verdicts via
# ``tests/test_c12_trigger_phase_b_alignment.py``.
_C12_FAMILY_KEYS: tuple[str, ...] = (
    "name",
    "live_days",
    "n_trades",
    "kill_switch_fires",
    "drift_verdict",
)


def _normalise_families(
    families: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate per-family Phase-B telemetry blocks for the C12 trigger.

    Producer-side guardrail (Deep-Review 2026-04-27 MAJOR finding): each
    family must be a dict; keys outside ``_C12_FAMILY_KEYS`` are passed
    through (additive contract); missing required keys raise
    ``ValueError`` at producer-time so the broken payload never reaches
    the trigger as ``UNEVALUABLE``.
    """
    if not isinstance(families, list):
        raise TypeError(
            f"families must be a list, got {type(families).__name__}",
        )
    out: list[dict[str, Any]] = []
    for idx, fam in enumerate(families):
        if not isinstance(fam, dict):
            raise TypeError(
                f"families[{idx}] must be a dict, got {type(fam).__name__}",
            )
        missing = [k for k in _C12_FAMILY_KEYS if k not in fam]
        if missing:
            raise ValueError(
                f"families[{idx}] missing required keys for the C12 "
                f"trigger contract: {missing} (see "
                "scripts/check_c12_trigger.py for the consumer schema)",
            )
        out.append(dict(fam))
    return out


def build_public_report(
    cal_payload: dict[str, Any] | None,
    *,
    source_path: Path | None,
    source_commit_sha: str | None,
    source_workflow_run: str | None,
    track_record_gate: dict[str, Any] | None = None,
    regime_stratified: dict[str, Any] | None = None,
    families: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construct the public-report dict from a calibration artifact.

    A ``None`` payload yields a status=``awaiting_first_run`` shell so the
    dashboard can render a useful "no data yet" panel instead of a 404.

    ``track_record_gate`` (additive in schema 1.1.0): when supplied, the
    serialised verdict from
    :func:`scripts.track_record_gate.evaluate_track_record_gate` is
    surfaced under the ``track_record_gate`` key so the dashboard can
    render the C2-C6 inference layer alongside the calibration block.

    ``regime_stratified`` (additive in schema 1.2.0): when supplied, the
    per-regime metrics produced by
    :mod:`scripts.regime_stratification` are surfaced under the
    ``regime_stratified`` key (one block per regime label plus the
    aggregate freq-weighted Sharpe and BH-FDR rejection summary).

    ``families`` (additive in schema 1.3.0; Deep-Review 2026-04-27 MAJOR
    finding): per-family Phase-B incubation telemetry consumed by
    :mod:`scripts.check_c12_trigger`. Each entry must be a dict carrying
    at minimum ``name``, ``live_days`` (int), ``n_trades`` (int),
    ``kill_switch_fires`` (int >= 0), ``drift_verdict`` (str). The
    trigger consumer documents the contract; this producer hook closes
    the previously-undocumented producer/consumer gap so the GREEN-path
    is end-to-end testable. Pass ``None`` when no families have entered
    Phase-B yet (the trigger will return BLOCKED, which is the correct
    pre-Phase-B state).
    """
    now = datetime.now(UTC).isoformat()
    if cal_payload is None:
        out = {
            "schema_version": PUBLIC_SCHEMA_VERSION,
            "generated_at": now,
            "status": "awaiting_first_run",
            "source": {
                "path": None,
                "commit_sha": source_commit_sha,
                "workflow_run": source_workflow_run,
            },
        }
        if track_record_gate is not None:
            out["track_record_gate"] = track_record_gate
        if regime_stratified is not None:
            out["regime_stratified"] = regime_stratified
        if families is not None:
            out["families"] = _normalise_families(families)
        return out

    metrics = _extract_calibration_metrics(cal_payload)
    n_events = _extract_n_events(cal_payload)
    weighted_hr = _extract_weighted_hit_rate(cal_payload)
    family_weights_raw = cal_payload.get("family_weights") or {}
    family_weights: dict[str, float] = {}
    for fam, w in family_weights_raw.items():
        v = _coerce_float(w)
        if v is not None:
            family_weights[str(fam)] = round(v, 6)

    out = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "generated_at": now,
        "status": "ok",
        "n_events": n_events,
        "weighted_hit_rate": weighted_hr,
        "family_weights": family_weights,
        "metrics": metrics,
        "source": {
            "path": str(source_path) if source_path else None,
            "commit_sha": source_commit_sha,
            "workflow_run": source_workflow_run,
        },
    }
    if track_record_gate is not None:
        out["track_record_gate"] = track_record_gate
    if regime_stratified is not None:
        out["regime_stratified"] = regime_stratified
    if families is not None:
        out["families"] = _normalise_families(families)
    return out


def append_public_history(
    output_path: Path,
    report: dict[str, Any],
    *,
    history_filename: str = DEFAULT_HISTORY_FILENAME,
    retention: int = HISTORY_RETENTION,
) -> Path:
    """Append a compact history line for the dashboard sparkline.

    Skips the append silently when ``status != "ok"`` so the
    ``awaiting_first_run`` placeholder doesn't dilute the trend feed.
    Truncates to ``retention`` entries when needed.
    """
    history_path = output_path.with_name(history_filename)
    if report.get("status") != "ok":
        # Make sure the file at least exists for the dashboard fetch.
        history_path.parent.mkdir(parents=True, exist_ok=True)
        if not history_path.exists():
            atomic_write_text("", history_path)
        return history_path

    entry = {
        "timestamp": report.get("generated_at"),
        "n_events": report.get("n_events"),
        "weighted_hit_rate": report.get("weighted_hit_rate"),
        "metrics": report.get("metrics") or {},
        "source_commit_sha": (report.get("source") or {}).get("commit_sha"),
    }

    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    existing.append(entry)
    if len(existing) > retention:
        existing = existing[-retention:]

    atomic_write_text("\n".join(json.dumps(e, sort_keys=True) for e in existing) + "\n", history_path)
    return history_path


def write_report(report: dict[str, Any], output_path: Path) -> None:
    """Atomically write the public report JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(output_path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit the public calibration report (Q3/Q4 §3.1.1).",
    )
    parser.add_argument(
        "--input-cal",
        type=Path,
        default=None,
        help="Path to a zone_priority(_contextual)_calibration.json. "
        "When omitted, the latest matching file under "
        f"{DEFAULT_SEARCH_DIR}/ is used.",
    )
    parser.add_argument(
        "--search-dir",
        type=Path,
        default=DEFAULT_SEARCH_DIR,
        help=f"Directory to scan when --input-cal is omitted (default: {DEFAULT_SEARCH_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination for the public JSON (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--commit-sha",
        default=os.environ.get("GITHUB_SHA"),
        help="Source commit SHA (default: $GITHUB_SHA).",
    )
    parser.add_argument(
        "--workflow-run",
        default=os.environ.get("GITHUB_RUN_ID"),
        help="Source workflow run id (default: $GITHUB_RUN_ID).",
    )
    parser.add_argument(
        "--include-families",
        type=Path,
        default=None,
        help=(
            "Optional path to a families telemetry JSON (output of "
            "scripts/build_families_telemetry.py). When provided, the "
            "families[] block is embedded into the public report so the "
            "C12 trigger can evaluate per-family Phase-B promotion."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _parse_args(argv)

    cal_path: Path | None = args.input_cal
    if cal_path is None:
        cal_path = _find_latest_calibration_artifact(args.search_dir)

    cal_payload: dict[str, Any] | None = None
    if cal_path is not None:
        try:
            cal_payload = json.loads(cal_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"ERROR: malformed calibration JSON at {cal_path}: {exc}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"ERROR: cannot read calibration source {cal_path}: {exc}", file=sys.stderr)
            return 1

    families: list[dict[str, Any]] | None = None
    if args.include_families is not None:
        try:
            fam_payload = json.loads(args.include_families.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: malformed families telemetry JSON at {args.include_families}: {exc}",
                file=sys.stderr,
            )
            return 1
        except OSError as exc:
            print(
                f"ERROR: cannot read families telemetry {args.include_families}: {exc}",
                file=sys.stderr,
            )
            return 1
        if not isinstance(fam_payload, dict) or "families" not in fam_payload:
            print(
                f"ERROR: families telemetry at {args.include_families} "
                "missing top-level 'families' key (expected producer schema "
                "from scripts/build_families_telemetry.py).",
                file=sys.stderr,
            )
            return 1
        families = fam_payload["families"]

    try:
        report = build_public_report(
            cal_payload,
            source_path=cal_path,
            source_commit_sha=args.commit_sha,
            source_workflow_run=args.workflow_run,
            families=families,
        )
    except (TypeError, ValueError) as exc:
        print(
            f"ERROR: families telemetry rejected by C12 contract: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        write_report(report, args.output)
    except OSError as exc:
        print(f"ERROR: cannot write public report to {args.output}: {exc}", file=sys.stderr)
        return 1

    history_path = append_public_history(args.output, report)

    print(f"Public calibration report: status={report['status']} output={args.output} history={history_path}")
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
