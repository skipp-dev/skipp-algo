"""Integration tests pinning the C7 producer↔consumer schema contract.

These tests fail loudly if a downstream rename in either
``scripts.build_dashboard_payload`` (producer) or any of the
``terminal_tabs.tab_*`` modules (consumer) reintroduces the
2026-04-26 schema-mismatch incident. Every consumer alias the
producer emits is exercised here, and the integration runs on
realistic fixture inputs (one variant, all five sprint outputs).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.build_dashboard_payload import build_dashboard_payload
from terminal_tabs.tab_calibration_detail import build_detail
from terminal_tabs.tab_track_record import build_summary

_FROZEN_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _seed(cache_dir: Path, date: str = "2026-04-26") -> str:
    """Seed one variant with all five sprint outputs + sub-blocks."""
    vk = {"setup_type": "smc_breaker", "symbol_group": "btc"}
    _write(
        cache_dir / f"walk_forward_{date}.json",
        {
            "variants": [
                {
                    **vk,
                    "regime": "RISK_ON",
                    "n_trades": 142,
                    "hit_rate": 0.58,
                    "sharpe": 0.93,
                    "wfe": 0.62,
                    "max_dd": 0.094,
                    "walk_forward_mode": "anchored",
                    "walk_forward_folds": [
                        {"sharpe": 0.81},
                        {"sharpe": 1.02},
                        {"sharpe": 0.96},
                    ],
                }
            ]
        },
    )
    _write(
        cache_dir / f"bootstrap_ci_{date}.json",
        {
            "variants": [
                {
                    **vk,
                    "sharpe_ci_low": 0.42,
                    "sharpe_ci_high": 1.31,
                    "n_bootstraps": 5000,
                    "sharpe_samples": [0.5, 0.8, 1.1],
                }
            ]
        },
    )
    _write(
        cache_dir / f"permutation_{date}.json",
        {
            "variants": [
                {
                    **vk,
                    "p_value": 0.018,
                    "bh_fdr_pass": True,
                    "schema": "outcome_sign",
                    "observed": 0.93,
                    "null_samples": [0.1, 0.05, -0.02],
                }
            ]
        },
    )
    _write(
        cache_dir / f"regime_stratified_{date}.json",
        {
            "variants": [
                {
                    **vk,
                    "regime_concentration": 0.71,
                    "aggregate_freq_weighted_sharpe": 0.88,
                    "regime_concentration_warning": False,
                    "per_regime": {
                        "RISK_ON": {"n_trades": 100, "sharpe": 1.02},
                        "RISK_OFF": {"n_trades": 42, "sharpe": 0.51},
                    },
                }
            ]
        },
    )
    _write(
        cache_dir / f"psr_mintrl_{date}.json",
        {"variants": [{**vk, "psr_at_0": 0.91, "min_trl_at_0": 168}]},
    )
    return date


def test_producer_emits_all_consumer_aliases(tmp_path: Path) -> None:
    """Every key the C7 tabs read must exist on the producer output."""
    _seed(tmp_path)
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    assert len(payload["variants"]) == 1
    v = payload["variants"][0]

    # Aliases consumed by tab_track_record.format_variant_row.
    assert v["variant"] == "smc_breaker_btc"
    assert v["sharpe_ci_low"] == pytest.approx(0.42)
    assert v["sharpe_ci_high"] == pytest.approx(1.31)
    assert v["permutation_p_value"] == pytest.approx(0.018)
    assert v["psr"] == pytest.approx(0.91)
    assert v["walk_forward_efficiency"] == pytest.approx(0.62)
    assert v["max_drawdown"] == pytest.approx(0.094)

    # Sub-blocks consumed by tab_calibration_detail.
    assert isinstance(v["bootstrap"], dict) and v["bootstrap"]["sharpe_samples"]
    assert isinstance(v["permutation"], dict) and v["permutation"]["null_samples"]
    assert isinstance(v["regime_stratified"], dict)
    assert "RISK_ON" in v["regime_stratified"]
    assert v["walk_forward_folds"]


def test_tab_track_record_renders_producer_payload(tmp_path: Path) -> None:
    _seed(tmp_path)
    gate = {"status": "yellow", "n_trades": 142, "checks": [], "summary": {}}
    payload = build_dashboard_payload(
        tmp_path, track_record_gate=gate, now=_FROZEN_NOW
    )
    summary = build_summary(payload)
    assert summary["status"] == "ok"
    assert len(summary["rows"]) == 1
    row = summary["rows"][0]
    # Critical: variant label + numeric columns must populate, not stay None.
    assert row["variant"] == "smc_breaker_btc"
    assert row["n"] == 142
    assert row["sharpe"] == pytest.approx(0.93)
    assert row["sharpe_ci_low"] == pytest.approx(0.42)
    assert row["permutation_p"] == pytest.approx(0.018)
    assert row["psr"] == pytest.approx(0.91)
    assert row["wfe"] == pytest.approx(0.62)
    assert row["max_dd"] == pytest.approx(0.094)
    assert row["gate_status"] == "amber"


def test_tab_calibration_detail_renders_producer_subblocks(tmp_path: Path) -> None:
    _seed(tmp_path)
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    detail = build_detail(payload, "smc_breaker_btc")
    assert detail["status"] == "ok"
    assert detail["walk_forward"]["available"] is True
    assert detail["walk_forward"]["n_folds"] == 3
    assert detail["bootstrap"]["available"] is True
    assert detail["bootstrap"]["ci_low"] == pytest.approx(0.42)
    assert detail["permutation"]["available"] is True
    assert detail["permutation"]["p_value"] == pytest.approx(0.018)
    assert detail["regime"]["available"] is True
    assert "RISK_ON" in detail["regime"]["per_regime"]
    assert detail["psr_min_trl"]["available"] is True
    assert detail["psr_min_trl"]["psr"] == pytest.approx(0.91)


def test_per_variant_gate_overrides_global(tmp_path: Path) -> None:
    _seed(tmp_path)
    gate = {
        "status": "green",  # global
        "n_trades": 142,
        "checks": [],
        "summary": {},
        "per_variant": {
            "smc_breaker_btc": {
                "status": "red",
                "failures": ["sharpe_ci_low<0.3", "psr<0.95"],
            }
        },
    }
    payload = build_dashboard_payload(
        tmp_path, track_record_gate=gate, now=_FROZEN_NOW
    )
    v = payload["variants"][0]
    assert v["gate_status"] == "red"
    assert "sharpe_ci_low<0.3" in v["gate_failures"]


def test_per_variant_gate_falls_back_to_global(tmp_path: Path) -> None:
    """When per_variant block is absent, the global status is mirrored."""
    _seed(tmp_path)
    gate = {"status": "yellow", "n_trades": 142, "checks": [], "summary": {}}
    payload = build_dashboard_payload(
        tmp_path, track_record_gate=gate, now=_FROZEN_NOW
    )
    assert payload["variants"][0]["gate_status"] == "amber"
