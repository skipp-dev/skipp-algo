"""Tests for Amendment A1.B — D4 FVG-Quality recalibration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fvg_quality_recalibration import (
    FEATURE_KEYS,
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
    assert payload["report_version"] == "1.0"
    assert payload["status"] == "ok"
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
