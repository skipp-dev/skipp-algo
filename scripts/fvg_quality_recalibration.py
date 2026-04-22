"""Amendment A1.B — D4 FVG-Quality recalibration on per-event ledgers.

Reads JSONL ledgers emitted by the harness (Amendment A1.A
``smc_core/event_ledger.py``) and re-fits the FVG quality weights
against the realised ``outcome`` labels. Writes a *shadow* JSON to
``artifacts/reports/fvg_quality_calibration_shadow.json`` — production
weights in :mod:`smc_core.fvg_quality` stay pinned until G3 A/B
(Amendment A1.E) signs off.

Acceptance gate (Amendment A1.B → production):

* Top-quartile HR ≥ 0.70
* Bottom-quartile HR ≤ 0.55
* Quality-score Spearman correlation with outcome ≥ 0.20

The CLI is fail-soft: a corpus that lacks the per-event feature
fields (``gap_size_atr`` / ``hurst_50`` / ``htf_aligned`` /
``distance_to_price_atr`` / ``is_full_body``) emits a shadow JSON with
``status=insufficient_features`` rather than crashing — that is the
expected state until the enrichers are wired in a follow-up batch.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smc_core.event_ledger import read_event_ledger  # noqa: E402

REPORT_VERSION = "1.1"
WEIGHT_CAP_LO = 0.05
WEIGHT_CAP_HI = 0.40
MIN_FVG_EVENTS = 30
QUARTILE_MIN_EVENTS = 8
ACCEPT_TOP_HR = 0.70
ACCEPT_BOTTOM_HR = 0.55
ACCEPT_SPEARMAN = 0.20

# Outcome label source. ``outcome`` keeps the legacy lenient label
# (touch-anchor mitigation) used by Amendment A1.B since day one.
# ``partial_50`` switches to the strict ``features.label_partial_50``
# label promoted by D1/D3 of the Q3 FVG audit. Adding new sources
# here is the single place you need to touch.
LABEL_SOURCES: tuple[str, ...] = ("outcome", "partial_50")
DEFAULT_LABEL_SOURCE = "outcome"

# Order is meaningful: it pins the column order of feature matrices
# downstream and matches the legacy weight table in fvg_quality.py.
FEATURE_KEYS: tuple[str, ...] = (
    "gap_size_atr",
    "htf_aligned",
    "distance_to_price_atr",
    "is_full_body",
    "hurst_50",
)
LEGACY_WEIGHTS = {
    "gap_size_atr": 0.30,
    "htf_aligned": 0.25,
    "distance_to_price_atr": 0.15,
    "is_full_body": 0.10,
    "hurst_50": 0.20,
}


@dataclass(slots=True)
class QuartileStat:
    """Hit-rate + sample-size for one score-quartile bucket."""

    quartile: int  # 1..4 (1 = lowest score)
    n: int
    hits: int
    hit_rate: float


@dataclass(slots=True)
class RecalibrationReport:
    """Top-level shadow record. Mirrors what the CLI writes to disk."""

    report_version: str = REPORT_VERSION
    status: str = "ok"
    label_source: str = DEFAULT_LABEL_SOURCE
    n_events_total: int = 0
    n_fvg_events: int = 0
    n_with_features: int = 0
    n_with_label: int = 0
    weights_legacy: dict[str, float] = field(default_factory=dict)
    weights_shadow: dict[str, float] = field(default_factory=dict)
    quartiles: list[QuartileStat] = field(default_factory=list)
    spearman_score_outcome: float = float("nan")
    acceptance: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def iter_fvg_events(ledger_paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    """Yield FVG-only records from one or more JSONL ledgers."""
    for path in ledger_paths:
        for record in read_event_ledger(path):
            if record.get("family") == "FVG":
                yield record


def _row_features(record: dict[str, Any]) -> dict[str, float] | None:
    """Pull the five quality features from a ledger record.

    Returns ``None`` if any required feature is missing or non-finite.
    The ``htf_aligned`` and ``is_full_body`` fields may live either in
    ``features`` (D4 enricher) or in ``context`` (legacy harness) — we
    accept either source so the script keeps working as enrichers
    migrate.
    """
    features = record.get("features") or {}
    context = record.get("context") or {}

    def _float(key: str) -> float | None:
        if key in features:
            value = features[key]
        elif key in context:
            value = context[key]
        else:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return value

    def _bool_to_float(key: str) -> float | None:
        if key in features:
            return 1.0 if features[key] else 0.0
        if key in context:
            return 1.0 if context[key] in (True, "true", "True", "1", 1) else 0.0
        return None

    gap = _float("gap_size_atr")
    dist = _float("distance_to_price_atr")
    hurst = _float("hurst_50")
    htf = _bool_to_float("htf_aligned")
    full_body = _bool_to_float("is_full_body")
    if None in (gap, dist, hurst, htf, full_body):
        return None
    return {
        "gap_size_atr": gap,
        "htf_aligned": htf,
        "distance_to_price_atr": dist,
        "is_full_body": full_body,
        "hurst_50": hurst,
    }


def _zscore(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(len(values), 1)
    std = math.sqrt(var) if var > 0 else 1.0
    return [(v - mean) / std for v in values]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _logistic(x: float) -> float:
    if x >= 0:
        ez = math.exp(-x)
        return 1.0 / (1.0 + ez)
    ez = math.exp(x)
    return ez / (1.0 + ez)


def _l2_logreg(
    matrix: list[list[float]],
    labels: list[int],
    *,
    l2: float = 1.0,
    epochs: int = 200,
    lr: float = 0.05,
) -> tuple[list[float], float]:
    """Tiny pure-Python L2 logistic regression (gradient descent).

    Returns ``(beta, bias)``. Deterministic, dependency-free; sufficient
    for the small sample sizes we operate on (≤ 10 000 FVG events).
    """
    n_features = len(matrix[0]) if matrix else 0
    beta = [0.0] * n_features
    bias = 0.0
    n = len(labels)
    if n == 0:
        return beta, bias
    for _ in range(epochs):
        grad_beta = [0.0] * n_features
        grad_bias = 0.0
        for row, y in zip(matrix, labels):
            z = bias + sum(b * x for b, x in zip(beta, row))
            p = _logistic(z)
            err = p - y
            grad_bias += err
            for j, x in enumerate(row):
                grad_beta[j] += err * x
        for j in range(n_features):
            grad_beta[j] = grad_beta[j] / n + l2 * beta[j]
            beta[j] -= lr * grad_beta[j]
        bias -= lr * (grad_bias / n)
    return beta, bias


def _normalise_to_weights(beta: list[float]) -> dict[str, float]:
    """Convert raw logistic coefficients to capped, sum-1 weights."""
    abs_beta = [abs(b) for b in beta]
    total = sum(abs_beta) or 1.0
    raw = {key: abs_beta[i] / total for i, key in enumerate(FEATURE_KEYS)}
    capped = {key: _clamp(value, WEIGHT_CAP_LO, WEIGHT_CAP_HI) for key, value in raw.items()}
    cap_total = sum(capped.values()) or 1.0
    return {key: round(value / cap_total, 4) for key, value in capped.items()}


def _quartiles(scores: list[float], outcomes: list[int]) -> list[QuartileStat]:
    if not scores:
        return []
    paired = sorted(zip(scores, outcomes), key=lambda x: x[0])
    n = len(paired)
    cuts = [n // 4, n // 2, (3 * n) // 4]
    buckets: list[list[tuple[float, int]]] = [[], [], [], []]
    for idx, item in enumerate(paired):
        if idx < cuts[0]:
            buckets[0].append(item)
        elif idx < cuts[1]:
            buckets[1].append(item)
        elif idx < cuts[2]:
            buckets[2].append(item)
        else:
            buckets[3].append(item)
    stats: list[QuartileStat] = []
    for q, bucket in enumerate(buckets, start=1):
        if not bucket:
            stats.append(QuartileStat(quartile=q, n=0, hits=0, hit_rate=float("nan")))
            continue
        hits = sum(o for _, o in bucket)
        stats.append(
            QuartileStat(
                quartile=q,
                n=len(bucket),
                hits=hits,
                hit_rate=round(hits / len(bucket), 4),
            )
        )
    return stats


def _spearman(scores: list[float], outcomes: list[int]) -> float:
    n = len(scores)
    if n < 2:
        return float("nan")
    rank_score = _rank(scores)
    rank_out = _rank([float(o) for o in outcomes])
    diffs = [(a - b) ** 2 for a, b in zip(rank_score, rank_out)]
    rho = 1 - (6 * sum(diffs)) / (n * (n * n - 1))
    return round(rho, 4)


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _resolve_outcome(record: dict[str, Any], label_source: str) -> int | None:
    """Pick the binary outcome label from a ledger record.

    Returns ``None`` if the requested label is missing or non-binary so
    the caller can drop the row instead of biasing the fit. The legacy
    ``outcome`` source treats any falsy/missing value as 0; the strict
    ``partial_50`` source requires an explicit boolean in
    ``features.label_partial_50``.
    """
    if label_source == "outcome":
        if record.get("outcome") is None:
            return None
        return 1 if record.get("outcome") else 0
    if label_source == "partial_50":
        features = record.get("features") or {}
        value = features.get("label_partial_50")
        if value is None:
            return None
        if isinstance(value, bool):
            return 1 if value else 0
        if value in (1, 0):
            return int(value)
        return None
    raise ValueError(f"unknown label_source: {label_source!r}")


def recalibrate(
    ledger_paths: list[Path],
    *,
    label_source: str = DEFAULT_LABEL_SOURCE,
) -> RecalibrationReport:
    """Run the full recalibration pipeline and return a report."""
    if label_source not in LABEL_SOURCES:
        raise ValueError(
            f"label_source must be one of {LABEL_SOURCES!r}, got {label_source!r}"
        )
    report = RecalibrationReport(
        label_source=label_source,
        weights_legacy=dict(LEGACY_WEIGHTS),
    )
    rows: list[dict[str, float]] = []
    outcomes: list[int] = []
    n_total = 0
    n_fvg = 0
    n_with_label = 0
    for record in iter_fvg_events(ledger_paths):
        n_total += 1
        n_fvg += 1
        label = _resolve_outcome(record, label_source)
        if label is None:
            continue
        n_with_label += 1
        feats = _row_features(record)
        if feats is None:
            continue
        rows.append(feats)
        outcomes.append(label)

    report.n_events_total = n_total
    report.n_fvg_events = n_fvg
    report.n_with_features = len(rows)
    report.n_with_label = n_with_label

    if len(rows) < MIN_FVG_EVENTS:
        # If FVG event count itself is the bottleneck, label that. If we
        # have plenty of FVG events but no rows survived feature
        # extraction, the enricher is the bottleneck instead.
        if n_fvg < MIN_FVG_EVENTS:
            report.status = "insufficient_events"
        else:
            report.status = "insufficient_features"
        report.notes.append(
            f"need >= {MIN_FVG_EVENTS} FVG events with all five features; "
            f"have {len(rows)} (of {n_fvg} FVG events)."
        )
        return report

    matrix_raw = [[row[k] for k in FEATURE_KEYS] for row in rows]
    columns = list(zip(*matrix_raw))
    z_columns = [_zscore(list(col)) for col in columns]
    matrix = [list(r) for r in zip(*z_columns)]

    beta, _bias = _l2_logreg(matrix, outcomes)
    report.weights_shadow = _normalise_to_weights(beta)

    scores = []
    for row in rows:
        s = sum(report.weights_shadow[k] * row[k] for k in FEATURE_KEYS)
        scores.append(s)

    quartiles = _quartiles(scores, outcomes)
    report.quartiles = quartiles
    report.spearman_score_outcome = _spearman(scores, outcomes)

    top = quartiles[-1] if quartiles else None
    bottom = quartiles[0] if quartiles else None
    report.acceptance = {
        "top_quartile_hr_ge_0_70": bool(
            top is not None
            and top.n >= QUARTILE_MIN_EVENTS
            and top.hit_rate >= ACCEPT_TOP_HR
        ),
        "bottom_quartile_hr_le_0_55": bool(
            bottom is not None
            and bottom.n >= QUARTILE_MIN_EVENTS
            and bottom.hit_rate <= ACCEPT_BOTTOM_HR
        ),
        "spearman_ge_0_20": bool(
            not math.isnan(report.spearman_score_outcome)
            and report.spearman_score_outcome >= ACCEPT_SPEARMAN
        ),
    }
    if not all(report.acceptance.values()):
        report.notes.append(
            "shadow weights computed but acceptance gate not yet met; "
            "production weights remain pinned per Amendment A1.B."
        )
    return report


def write_shadow_json(report: RecalibrationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    payload["quartiles"] = [asdict(q) for q in report.quartiles]
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        required=True,
        help="Root directory containing events_<sym>_<tf>.jsonl files (recursive).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "artifacts/reports/fvg_quality_calibration_shadow.json",
    )
    parser.add_argument(
        "--label-source",
        choices=LABEL_SOURCES,
        default=DEFAULT_LABEL_SOURCE,
        help=(
            "Outcome label to fit against. 'outcome' = legacy lenient "
            "hit (default); 'partial_50' = strict features.label_partial_50 "
            "promoted in the Q3 FVG audit (D1/D3)."
        ),
    )
    args = parser.parse_args(argv)

    paths = sorted(args.corpus_dir.rglob("events_*.jsonl"))
    report = recalibrate(paths, label_source=args.label_source)
    write_shadow_json(report, args.output)
    accept_status = "PASS" if report.acceptance and all(report.acceptance.values()) else "PENDING"
    print(
        f"FVG-Quality recal status={report.status} "
        f"label={report.label_source} "
        f"n_fvg={report.n_fvg_events} n_with_label={report.n_with_label} "
        f"n_with_features={report.n_with_features} "
        f"acceptance={accept_status} "
        f"shadow={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
