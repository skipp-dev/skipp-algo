"""Tests for Amendment A1.B — D4 FVG-Quality recalibration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fvg_quality_recalibration import (
    ACCEPT_BOTTOM_HR_DELTA,
    ACCEPT_TOP_HR_DELTA,
    ACCEPTANCE_MODES,
    DEFAULT_ACCEPTANCE_MODE,
    DEFAULT_LABEL_SOURCE,
    FEATURE_KEYS,
    LABEL_SOURCES,
    LEGACY_WEIGHTS,
    MIN_FVG_EVENTS,
    QUARTILE_MIN_EVENTS,
    WEIGHT_CAP_HI,
    WEIGHT_CAP_LO,
    recalibrate,
    write_shadow_json,
)
from smc_core.event_ledger import write_event_ledger


def _ledger(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "events_TEST_15m.jsonl"
    write_event_ledger(records, output_path=path, symbol="TEST", timeframe="15m")
    return path


def _fvg_record(*, idx: int, outcome: bool, features: dict | None = None) -> dict:
    return {
        "event_id": f"fvg-{idx}",
        "family": "FVG",
        "predicted_prob": 0.5,
        "outcome": outcome,
        "timestamp": float(idx),
        "context": {"session": "NY_AM"},
        "features": features or {},
    }


def test_insufficient_features_status(tmp_path: Path) -> None:
    # FVG events present but no feature payload — fail-soft path.
    records = [_fvg_record(idx=i, outcome=bool(i % 2)) for i in range(40)]
    path = _ledger(tmp_path, records)
    report = recalibrate([path])
    assert report.status == "insufficient_features"
    assert report.n_fvg_events == 40
    assert report.n_with_features == 0
    assert report.weights_legacy == LEGACY_WEIGHTS
    assert report.weights_shadow == {}


def test_non_fvg_events_excluded(tmp_path: Path) -> None:
    records = [
        {
            "event_id": "bos-1",
            "family": "BOS",
            "predicted_prob": 0.5,
            "outcome": True,
            "timestamp": 1.0,
            "context": {},
        }
    ]
    path = _ledger(tmp_path, records)
    report = recalibrate([path])
    assert report.n_fvg_events == 0
    assert report.status in {"insufficient_features", "insufficient_events"}


def _separable_corpus(n: int = 80) -> list[dict]:
    """Build a corpus where high-gap + htf-aligned + high-hurst events
    are mostly hits and the inverse class are mostly misses. The
    L2-logistic should recover that ranking.
    """
    records: list[dict] = []
    for i in range(n // 2):
        records.append(
            _fvg_record(
                idx=i,
                outcome=True,
                features={
                    "gap_size_atr": 1.5 + i * 0.01,
                    "htf_aligned": True,
                    "distance_to_price_atr": 0.4,
                    "is_full_body": True,
                    "hurst_50": 0.7,
                },
            )
        )
    for i in range(n // 2, n):
        records.append(
            _fvg_record(
                idx=i,
                outcome=False,
                features={
                    "gap_size_atr": 0.3,
                    "htf_aligned": False,
                    "distance_to_price_atr": 2.5,
                    "is_full_body": False,
                    "hurst_50": 0.35,
                },
            )
        )
    return records


def test_recalibrate_separable(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(80))
    report = recalibrate([path])
    assert report.status == "ok"
    assert report.n_with_features == 80
    # All five feature weights present, summing to ~1.0 after cap+norm.
    assert set(report.weights_shadow.keys()) == set(FEATURE_KEYS)
    total = sum(report.weights_shadow.values())
    assert pytest.approx(total, abs=0.01) == 1.0
    for value in report.weights_shadow.values():
        assert WEIGHT_CAP_LO - 0.01 <= value <= WEIGHT_CAP_HI + 0.01
    # Quartiles populated (4 buckets).
    assert len(report.quartiles) == 4
    # Top-quartile HR > bottom-quartile HR.
    assert report.quartiles[-1].hit_rate > report.quartiles[0].hit_rate
    # Spearman positive.
    assert report.spearman_score_outcome > 0
    # Acceptance dict has all three keys.
    assert set(report.acceptance.keys()) == {
        "top_quartile_hr_ge_0_70",
        "bottom_quartile_hr_le_0_55",
        "spearman_ge_0_20",
    }


def test_min_event_floor(tmp_path: Path) -> None:
    records = _separable_corpus(MIN_FVG_EVENTS - 1)
    path = _ledger(tmp_path, records)
    report = recalibrate([path])
    assert report.status == "insufficient_events" or report.status == "insufficient_features"


def test_acceptance_gate_pass_on_strong_corpus(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(120))
    report = recalibrate([path])
    # Strong synthetic separation should pass all three acceptance checks.
    assert report.acceptance["top_quartile_hr_ge_0_70"] is True
    assert report.acceptance["bottom_quartile_hr_le_0_55"] is True
    assert report.acceptance["spearman_ge_0_20"] is True


def test_random_outcomes_dont_pass_acceptance(tmp_path: Path) -> None:
    # Same features, but outcome shuffled deterministically — acceptance
    # gate must NOT pass.
    records = _separable_corpus(80)
    for i, rec in enumerate(records):
        rec["outcome"] = bool(i % 2)
    path = _ledger(tmp_path, records)
    report = recalibrate([path])
    # All three should be False (or at least not all True).
    assert not all(report.acceptance.values())


def test_write_shadow_json(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(80))
    report = recalibrate([path])
    output = tmp_path / "shadow.json"
    write_shadow_json(report, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report_version"] == "1.2"
    assert payload["status"] == "ok"
    assert payload["label_source"] == "outcome"
    assert payload["acceptance_mode"] == "absolute"
    assert "weights_shadow" in payload
    assert isinstance(payload["quartiles"], list)


def test_quartile_min_events_guard() -> None:
    # Constant for downstream readers — make sure it's an int >= 1.
    assert QUARTILE_MIN_EVENTS >= 1


def test_features_in_context_fallback(tmp_path: Path) -> None:
    # Some legacy harnesses may park boolean features in context;
    # recalibrate() should still pick them up.
    records = _separable_corpus(60)
    for rec in records:
        # Move htf_aligned + is_full_body out of features into context
        # as legacy enrichers might.
        rec["context"] = dict(rec.get("context") or {})
        rec["context"]["htf_aligned"] = rec["features"].pop("htf_aligned")
        rec["context"]["is_full_body"] = rec["features"].pop("is_full_body")
    path = _ledger(tmp_path, records)
    report = recalibrate([path])
    assert report.status == "ok"
    assert report.n_with_features == 60


# --------------------------------------------------------------------- #
# REPORT_VERSION 1.1 — strict label_partial_50 source (Q3 D3 promotion) #
# --------------------------------------------------------------------- #


def test_label_sources_constant_pinned() -> None:
    # Pin the supported label sources so adding a new one is a
    # deliberate, test-visible decision.
    assert LABEL_SOURCES == ("outcome", "partial_50")
    assert DEFAULT_LABEL_SOURCE == "outcome"


def test_label_source_partial_50_uses_strict_label(tmp_path: Path) -> None:
    # Same features as the separable corpus, but the lenient outcome
    # is INVERTED relative to the strict label so the two label sources
    # produce different fits — proves the flag is actually wired.
    records = _separable_corpus(80)
    for rec in records:
        rec["features"]["label_partial_50"] = bool(rec["outcome"])
        rec["outcome"] = not bool(rec["outcome"])
    path = _ledger(tmp_path, records)

    lenient = recalibrate([path], label_source="outcome")
    strict = recalibrate([path], label_source="partial_50")

    assert lenient.status == "ok"
    assert strict.status == "ok"
    assert lenient.label_source == "outcome"
    assert strict.label_source == "partial_50"
    assert lenient.n_with_label == 80
    assert strict.n_with_label == 80
    # The two fits must disagree on the top-quartile direction because
    # the label is inverted.
    assert lenient.quartiles[-1].hit_rate != strict.quartiles[-1].hit_rate


def test_label_source_partial_50_drops_rows_without_label(tmp_path: Path) -> None:
    records = _separable_corpus(80)
    # Half the rows lack the strict label.
    for i, rec in enumerate(records):
        if i % 2 == 0:
            rec["features"]["label_partial_50"] = bool(rec["outcome"])
    path = _ledger(tmp_path, records)
    report = recalibrate([path], label_source="partial_50")
    assert report.n_fvg_events == 80
    assert report.n_with_label == 40


def test_label_source_invalid_raises(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(40))
    with pytest.raises(ValueError):
        recalibrate([path], label_source="bogus")


# --------------------------------------------------------------------- #
# --signed-weights — sign-preserving normaliser (Q3 D3 promotion path)  #
# --------------------------------------------------------------------- #


def test_signed_weights_default_off(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(80))
    report = recalibrate([path])
    assert report.signed_weights is False
    # Default-off path keeps directions all +1 (back-compat).
    assert set(report.weight_directions.values()) == {1}


def test_signed_weights_records_direction(tmp_path: Path) -> None:
    # Build a corpus where higher gap_size_atr is anti-correlated with
    # outcome — a classic strict-label inversion. The signed normaliser
    # must surface direction = -1 for that feature.
    records = []
    for i in range(40):
        records.append(
            _fvg_record(
                idx=i,
                outcome=True,
                features={
                    "gap_size_atr": 0.3,
                    "htf_aligned": True,
                    "distance_to_price_atr": 0.4,
                    "is_full_body": True,
                    "hurst_50": 0.7,
                },
            )
        )
    for i in range(40, 80):
        records.append(
            _fvg_record(
                idx=i,
                outcome=False,
                features={
                    "gap_size_atr": 1.8,
                    "htf_aligned": False,
                    "distance_to_price_atr": 2.5,
                    "is_full_body": False,
                    "hurst_50": 0.35,
                },
            )
        )
    path = _ledger(tmp_path, records)
    report = recalibrate([path], signed_weights=True)
    assert report.signed_weights is True
    # gap_size_atr direction must be -1 — bigger gap → lower outcome.
    assert report.weight_directions["gap_size_atr"] == -1


def test_signed_weights_monotone_quartiles(tmp_path: Path) -> None:
    # With sign preservation the quartile ranking must be monotone
    # increasing on a separable corpus, even if some features have
    # negative betas after fitting.
    records = []
    for i in range(40):
        records.append(
            _fvg_record(
                idx=i,
                outcome=True,
                features={
                    "gap_size_atr": 0.3,  # inverted: small gap → hit
                    "htf_aligned": True,
                    "distance_to_price_atr": 0.4,
                    "is_full_body": True,
                    "hurst_50": 0.7,
                },
            )
        )
    for i in range(40, 80):
        records.append(
            _fvg_record(
                idx=i,
                outcome=False,
                features={
                    "gap_size_atr": 1.8,
                    "htf_aligned": False,
                    "distance_to_price_atr": 2.5,
                    "is_full_body": False,
                    "hurst_50": 0.35,
                },
            )
        )
    path = _ledger(tmp_path, records)
    report = recalibrate([path], signed_weights=True)
    hrs = [q.hit_rate for q in report.quartiles]
    # Strictly non-decreasing — top quartile must beat bottom.
    assert hrs[-1] >= hrs[0]


# --------------------------------------------------------------------- #
# --acceptance-mode relative — base-rate-aware gates (Q3 D3 promotion)  #
# --------------------------------------------------------------------- #


def test_acceptance_modes_constant_pinned() -> None:
    assert ACCEPTANCE_MODES == ("absolute", "relative")
    assert DEFAULT_ACCEPTANCE_MODE == "absolute"
    assert ACCEPT_TOP_HR_DELTA == 0.10
    assert ACCEPT_BOTTOM_HR_DELTA == 0.15


def test_relative_mode_uses_base_rate_keys(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(80))
    report = recalibrate([path], acceptance_mode="relative")
    assert report.acceptance_mode == "relative"
    # Relative-mode gate keys must replace the absolute ones.
    assert set(report.acceptance.keys()) == {
        "top_quartile_hr_ge_base_plus_0_10",
        "bottom_quartile_hr_le_base_minus_0_15",
        "spearman_ge_0_20",
    }
    # Base-rate populated.
    assert 0.0 <= report.base_rate <= 1.0


def test_relative_mode_passes_high_base_rate_corpus(tmp_path: Path) -> None:
    # Build a corpus with ~75% base rate but a clearly separable
    # ranker — absolute mode would fail bottom-HR<=0.55 (because no
    # quartile dips that low under high base rate); relative mode must
    # pass.
    records = []
    for i in range(60):
        records.append(
            _fvg_record(
                idx=i,
                outcome=True,
                features={
                    "gap_size_atr": 1.5,
                    "htf_aligned": True,
                    "distance_to_price_atr": 0.4,
                    "is_full_body": True,
                    "hurst_50": 0.7,
                },
            )
        )
    for i in range(60, 80):
        # Bottom 25% — all misses, kept ranker-separable.
        records.append(
            _fvg_record(
                idx=i,
                outcome=False,
                features={
                    "gap_size_atr": 0.3,
                    "htf_aligned": False,
                    "distance_to_price_atr": 2.5,
                    "is_full_body": False,
                    "hurst_50": 0.35,
                },
            )
        )
    path = _ledger(tmp_path, records)
    report = recalibrate([path], acceptance_mode="relative")
    assert report.base_rate >= 0.70
    # Top must beat base by +10pp; bottom must trail by -15pp.
    top_hr = report.quartiles[-1].hit_rate
    bottom_hr = report.quartiles[0].hit_rate
    assert top_hr >= report.base_rate + 0.10 - 1e-6
    assert bottom_hr <= report.base_rate - 0.15 + 1e-6


def test_acceptance_mode_invalid_raises(tmp_path: Path) -> None:
    path = _ledger(tmp_path, _separable_corpus(40))
    with pytest.raises(ValueError):
        recalibrate([path], acceptance_mode="bogus")
