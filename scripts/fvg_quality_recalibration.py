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
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text  # noqa: E402

from smc_core.event_ledger import read_event_ledger

REPORT_VERSION = "2.0"
WEIGHT_CAP_LO = 0.05
WEIGHT_CAP_HI = 0.40
MIN_FVG_EVENTS = 30
QUARTILE_MIN_EVENTS = 8
ACCEPT_TOP_HR = 0.70
ACCEPT_BOTTOM_HR = 0.55
ACCEPT_SPEARMAN = 0.20

# Relative acceptance gate — base-rate aware. The strict ``partial_50``
# label has a ~80% positive base rate, so the absolute 0.55 floor for
# bottom-quartile HR cannot be hit even by a perfect ranker. Relative
# mode replaces the two HR gates with deltas around the corpus base
# rate. Spearman gate is unchanged (label-scale invariant).
ACCEPT_TOP_HR_DELTA = 0.10  # top quartile must beat base rate by +10pp
ACCEPT_BOTTOM_HR_DELTA = 0.15  # bottom quartile must trail by -15pp

ACCEPTANCE_MODES: tuple[str, ...] = ("absolute", "relative")
DEFAULT_ACCEPTANCE_MODE = "relative"

# Outcome label source. ``outcome`` keeps the legacy lenient label
# (touch-anchor mitigation) used by Amendment A1.B since day one.
# ``partial_50`` switches to the strict ``features.label_partial_50``
# label promoted by D1/D3 of the Q3 FVG audit. Adding new sources
# here is the single place you need to touch.
LABEL_SOURCES: tuple[str, ...] = ("outcome", "partial_50")
DEFAULT_LABEL_SOURCE = "partial_50"

# Order is meaningful: it pins the column order of feature matrices
# downstream and matches the legacy weight table in fvg_quality.py.
FEATURE_KEYS: tuple[str, ...] = (
    "gap_size_atr",
    "htf_aligned",
    "distance_to_price_atr",
    "is_full_body",
    "hurst_50",
)
LENIENT_WEIGHTS = {
    "gap_size_atr": 0.30,
    "htf_aligned": 0.25,
    "distance_to_price_atr": 0.15,
    "is_full_body": 0.10,
    "hurst_50": 0.20,
}
# Back-compat alias — some legacy memos / shadow JSON readers still
# import ``LEGACY_WEIGHTS``. Keep both names pointing at the same
# dict so we never break a downstream pin by accident.
LEGACY_WEIGHTS = LENIENT_WEIGHTS

# Promoted strict regime (Q3 D3, 2026-04-22). Mirrors the constants
# in ``smc_core.fvg_quality`` — DRY: keep both files in sync when
# the strict weights are re-tuned.
STRICT_WEIGHTS = {
    "gap_size_atr": 0.45,
    "htf_aligned": 0.0735,
    "distance_to_price_atr": 0.45,
    "is_full_body": 0.0515,
    "hurst_50": 0.0,
}
STRICT_DIRECTIONS = {
    "gap_size_atr": -1,
    "htf_aligned": -1,
    "distance_to_price_atr": -1,
    "is_full_body": -1,
    "hurst_50": 0,
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
    weight_directions: dict[str, int] = field(default_factory=dict)
    signed_weights: bool = True
    acceptance_mode: str = DEFAULT_ACCEPTANCE_MODE
    base_rate: float = float("nan")
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
        for row, y in zip(matrix, labels, strict=False):
            z = bias + sum(b * x for b, x in zip(beta, row, strict=False))
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


def _signed_directions(beta: list[float]) -> dict[str, int]:
    """Return per-feature direction (+1 / -1) preserved from the raw
    L2-logreg fit. A direction of -1 means the feature value should be
    *inverted* before being multiplied by the matching weight in
    :func:`_normalise_to_weights`. Zero-coefficient features are mapped
    to +1 so a downstream consumer never has to special-case them.
    """
    out: dict[str, int] = {}
    for i, key in enumerate(FEATURE_KEYS):
        out[key] = -1 if beta[i] < 0 else 1
    return out


def _score_with_directions(
    row: dict[str, float],
    weights: dict[str, float],
    directions: dict[str, int],
    means: dict[str, float],
) -> float:
    """Score one row honouring per-feature direction.

    Each feature is centred at its corpus mean before the sign is
    applied so a positive direction always means "above mean lifts the
    score" regardless of the raw feature scale.
    """
    total = 0.0
    for key in FEATURE_KEYS:
        centred = row[key] - means[key]
        total += weights[key] * directions[key] * centred
    return total


def _quartiles(scores: list[float], outcomes: list[int]) -> list[QuartileStat]:
    if not scores:
        return []
    paired = sorted(zip(scores, outcomes, strict=False), key=lambda x: x[0])
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
    diffs = [(a - b) ** 2 for a, b in zip(rank_score, rank_out, strict=False)]
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
    signed_weights: bool = True,
    acceptance_mode: str = DEFAULT_ACCEPTANCE_MODE,
) -> RecalibrationReport:
    """Run the full recalibration pipeline and return a report."""
    if label_source not in LABEL_SOURCES:
        raise ValueError(
            f"label_source must be one of {LABEL_SOURCES!r}, got {label_source!r}"
        )
    if acceptance_mode not in ACCEPTANCE_MODES:
        raise ValueError(
            f"acceptance_mode must be one of {ACCEPTANCE_MODES!r}, "
            f"got {acceptance_mode!r}"
        )
    report = RecalibrationReport(
        label_source=label_source,
        signed_weights=signed_weights,
        acceptance_mode=acceptance_mode,
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
    columns = list(zip(*matrix_raw, strict=False))
    z_columns = [_zscore(list(col)) for col in columns]
    matrix = [list(r) for r in zip(*z_columns, strict=False)]

    beta, _bias = _l2_logreg(matrix, outcomes)
    report.weights_shadow = _normalise_to_weights(beta)
    if signed_weights:
        report.weight_directions = _signed_directions(beta)
        means = {
            key: sum(row[key] for row in rows) / len(rows)
            for key in FEATURE_KEYS
        }
        scores = [
            _score_with_directions(
                row, report.weights_shadow, report.weight_directions, means
            )
            for row in rows
        ]
    else:
        report.weight_directions = {key: 1 for key in FEATURE_KEYS}
        scores = []
        for row in rows:
            s = sum(report.weights_shadow[k] * row[k] for k in FEATURE_KEYS)
            scores.append(s)

    quartiles = _quartiles(scores, outcomes)
    report.quartiles = quartiles
    report.spearman_score_outcome = _spearman(scores, outcomes)

    top = quartiles[-1] if quartiles else None
    bottom = quartiles[0] if quartiles else None
    base_rate = sum(outcomes) / len(outcomes) if outcomes else float("nan")
    report.base_rate = round(base_rate, 4) if outcomes else float("nan")
    if acceptance_mode == "absolute":
        top_threshold = ACCEPT_TOP_HR
        bottom_threshold = ACCEPT_BOTTOM_HR
        top_key = "top_quartile_hr_ge_0_70"
        bottom_key = "bottom_quartile_hr_le_0_55"
    else:
        top_threshold = base_rate + ACCEPT_TOP_HR_DELTA
        bottom_threshold = base_rate - ACCEPT_BOTTOM_HR_DELTA
        top_key = "top_quartile_hr_ge_base_plus_0_10"
        bottom_key = "bottom_quartile_hr_le_base_minus_0_15"
    report.acceptance = {
        top_key: bool(
            top is not None
            and top.n >= QUARTILE_MIN_EVENTS
            and top.hit_rate >= top_threshold
        ),
        bottom_key: bool(
            bottom is not None
            and bottom.n >= QUARTILE_MIN_EVENTS
            and bottom.hit_rate <= bottom_threshold
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
    atomic_write_text(json.dumps(payload, indent=2, default=str), path)


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
    parser.add_argument(
        "--signed-weights",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Preserve per-feature beta sign from the L2-logreg fit. "
            "Reports a `weight_directions` dict (+/-1 per feature) and "
            "computes scores with mean-centred, sign-adjusted features. "
            "Default ON since Q3 D3 promotion (2026-04-22) — pass "
            "`--no-signed-weights` to fall back to the legacy unsigned "
            "normaliser."
        ),
    )
    parser.add_argument(
        "--acceptance-mode",
        choices=ACCEPTANCE_MODES,
        default=DEFAULT_ACCEPTANCE_MODE,
        help=(
            "Acceptance gate scoring. 'absolute' = legacy fixed thresholds "
            "(top HR>=0.70, bottom HR<=0.55). 'relative' = base-rate "
            "aware (top HR>=base+0.10, bottom HR<=base-0.15) — required "
            "for high-base-rate labels like partial_50 where bottom-HR "
            "cannot drop to 0.55 even with a perfect ranker."
        ),
    )
    args = parser.parse_args(argv)

    paths = sorted(args.corpus_dir.rglob("events_*.jsonl"))
    report = recalibrate(
        paths,
        label_source=args.label_source,
        signed_weights=args.signed_weights,
        acceptance_mode=args.acceptance_mode,
    )
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
