"""Build the weekly promotion-gate dashboard artefact (closes #2354).

Reads archived promotion-gate reports from a source directory (default
``governance/promotion_decisions/``), buckets the per-family metrics by
ISO week, and writes a JSON + PNG artefact pair to
``artifacts/governance/`` for the weekly risk-owner review.

The script is intentionally fail-soft: if the source directory is empty
or missing, an empty-but-valid dashboard JSON is still emitted so the
weekly cron does not stay red while the archive seeds itself.

CLI
---
    python -m scripts.build_promotion_gate_dashboard \\
        --source-dir governance/promotion_decisions \\
        --output-dir artifacts/governance \\
        --lookback-weeks 12 \\
        --reference-date 2026-05-25
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from governance.promotion_gate import GateThresholds
from governance.promotion_report import (
    REPORT_SCHEMA_VERSION,
)
from scripts.smc_atomic_write import atomic_write_json

DASHBOARD_SCHEMA_VERSION = 1

DEFAULT_SOURCE_DIR = Path("governance") / "promotion_decisions"
DEFAULT_OUTPUT_DIR = Path("artifacts") / "governance"
DEFAULT_LOOKBACK_WEEKS = 12

# Metrics we surface on the dashboard. Keys must match
# ``Decision["metrics"]`` produced by ``governance.promotion_gate``.
METRIC_KEYS: tuple[str, ...] = ("brier", "ece", "fdr_pvalue", "psr", "psi")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing archived promotion-gate report JSONs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory the dashboard JSON + PNG are written into.",
    )
    parser.add_argument(
        "--lookback-weeks",
        type=int,
        default=DEFAULT_LOOKBACK_WEEKS,
        help="Trailing window in ISO weeks (default: 12).",
    )
    parser.add_argument(
        "--reference-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="ISO date used as the window anchor (default: today UTC).",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip PNG rendering (useful when matplotlib is unavailable).",
    )
    return parser.parse_args(argv)


def _parse_generated_at(value: object) -> datetime | None:
    """Parse a report ``generated_at`` ISO-8601 string into a UTC datetime."""
    if not isinstance(value, str):
        return None
    text = value.rstrip("Z")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_week_label(moment: datetime) -> str:
    """Return the canonical ``YYYY-Www`` ISO-week label for a datetime."""
    iso = moment.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _iso_week_window(reference: date, lookback_weeks: int) -> set[str]:
    """Enumerate the ISO-week labels in the trailing window ending today."""
    window: set[str] = set()
    cursor = datetime.combine(reference, datetime.min.time(), tzinfo=timezone.utc)
    for offset in range(lookback_weeks):
        window.add(_iso_week_label(cursor - timedelta(weeks=offset)))
    return window


def _iter_reports(source_dir: Path) -> Iterable[tuple[Path, Mapping[str, object]]]:
    if not source_dir.exists():
        return
    for report_path in sorted(source_dir.glob("*.json")):
        try:
            raw = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or "decisions" not in raw:
            continue
        yield report_path, raw


def _collect_points(
    source_dir: Path,
    window: set[str],
) -> list[dict[str, object]]:
    """Aggregate per-family per-week mean metrics across reports in window."""
    # bucket[(iso_week, family)][metric] -> list[float]
    bucket: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for _path, raw in _iter_reports(source_dir):
        moment = _parse_generated_at(raw.get("generated_at"))
        if moment is None:
            continue
        label = _iso_week_label(moment)
        if label not in window:
            continue
        decisions = load_decisions_from_report_via_raw(raw)
        for decision in decisions:
            family = decision.get("family")
            metrics = decision.get("metrics") or {}
            if not isinstance(family, str) or not isinstance(metrics, Mapping):
                continue
            for key in METRIC_KEYS:
                value = metrics.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    bucket[(label, family)][key].append(float(value))

    points: list[dict[str, object]] = []
    for (iso_week, family), per_metric in sorted(bucket.items()):
        point: dict[str, object] = {"iso_week": iso_week, "family": family}
        for key in METRIC_KEYS:
            values = per_metric.get(key) or []
            point[key] = sum(values) / len(values) if values else None
        points.append(point)
    return points


def load_decisions_from_report_via_raw(
    raw: Mapping[str, object],
) -> list[Mapping[str, object]]:
    """In-memory equivalent of ``load_decisions_from_report`` for parsed dicts."""
    decisions = raw.get("decisions")
    if not isinstance(decisions, list):
        return []
    return [d for d in decisions if isinstance(d, Mapping)]


def _threshold_payload(thresholds: GateThresholds) -> dict[str, float]:
    return {
        "brier_max": thresholds.brier_max,
        "ece_max": thresholds.ece_max,
        "fdr_q": thresholds.fdr_q,
        "psr_min": thresholds.psr_min,
        "psi_max": thresholds.psi_max,
    }


def _render_png(
    png_path: Path,
    points: list[dict[str, object]],
    thresholds: GateThresholds,
    reference: date,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    threshold_lookup = {
        "brier": thresholds.brier_max,
        "ece": thresholds.ece_max,
        "fdr_pvalue": thresholds.fdr_q,
        "psr": thresholds.psr_min,
        "psi": thresholds.psi_max,
    }

    fig, axes = plt.subplots(
        nrows=len(METRIC_KEYS), ncols=1, figsize=(10, 12), sharex=True
    )
    if not points:
        for ax, key in zip(axes, METRIC_KEYS):
            ax.set_title(f"{key} (no data in window)")
            ax.axhline(threshold_lookup[key], color="red", linestyle="--", linewidth=1)
        fig.suptitle(f"Promotion-gate dashboard — {reference.isoformat()} (empty)")
        fig.tight_layout()
        fig.savefig(png_path, dpi=110)
        plt.close(fig)
        return

    families = sorted({str(p["family"]) for p in points})
    weeks = sorted({str(p["iso_week"]) for p in points})
    week_to_x = {label: idx for idx, label in enumerate(weeks)}

    for ax, key in zip(axes, METRIC_KEYS):
        for family in families:
            xs: list[int] = []
            ys: list[float] = []
            for point in points:
                if point["family"] != family:
                    continue
                value = point.get(key)
                if value is None:
                    continue
                xs.append(week_to_x[str(point["iso_week"])])
                ys.append(float(value))
            if xs:
                ax.plot(xs, ys, marker="o", label=family)
        ax.axhline(
            threshold_lookup[key], color="red", linestyle="--", linewidth=1,
            label=f"gate ({threshold_lookup[key]:g})",
        )
        ax.set_ylabel(key)
        ax.grid(True, linewidth=0.3, alpha=0.5)
        ax.legend(loc="best", fontsize=8)

    axes[-1].set_xticks(list(week_to_x.values()))
    axes[-1].set_xticklabels(weeks, rotation=45, ha="right")
    axes[-1].set_xlabel("ISO week")
    fig.suptitle(f"Promotion-gate dashboard — {reference.isoformat()}")
    fig.tight_layout()
    fig.savefig(png_path, dpi=110)
    plt.close(fig)


def build(
    source_dir: Path,
    output_dir: Path,
    lookback_weeks: int,
    reference_date: date | None = None,
    render_png: bool = True,
) -> dict[str, Path]:
    """Build the dashboard artefacts and return paths to the written files."""
    if lookback_weeks <= 0:
        raise ValueError("lookback_weeks must be positive")

    reference = reference_date or datetime.now(timezone.utc).date()
    window = _iso_week_window(reference, lookback_weeks)
    points = _collect_points(source_dir, window)

    thresholds = GateThresholds()
    payload = {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference_date": reference.isoformat(),
        "lookback_weeks": lookback_weeks,
        "source_dir": str(source_dir),
        "gate_thresholds": _threshold_payload(thresholds),
        "points": points,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    reference_week = _iso_week_label(
        datetime.combine(reference, datetime.min.time(), tzinfo=timezone.utc)
    )
    json_path = output_dir / f"promotion_gate_dashboard_{reference_week}.json"
    atomic_write_json(payload, json_path, sort_keys=False)

    written: dict[str, Path] = {"json": json_path}
    if render_png:
        png_path = output_dir / f"promotion_gate_dashboard_{reference_week}.png"
        _render_png(png_path, points, thresholds, reference)
        written["png"] = png_path
    return written


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    written = build(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        lookback_weeks=args.lookback_weeks,
        reference_date=args.reference_date,
        render_png=not args.no_png,
    )
    for label, path in written.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
