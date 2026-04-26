"""Tests for terminal_tabs.tab_calibration_detail (C7/T4)."""

from __future__ import annotations

from terminal_tabs.tab_calibration_detail import (
    build_detail,
    find_variant,
)


def _payload() -> dict[str, object]:
    return {
        "variants": [
            {
                "variant": "smc_breaker_btc",
                "gate_status": "amber",
                "walk_forward_efficiency": 0.81,
                "walk_forward_mode": "rolling",
                "walk_forward_folds": [
                    {"sharpe": 0.7},
                    {"sharpe": 0.8},
                    {"sharpe": 0.9},
                ],
                "bootstrap": {
                    "sharpe_samples": [0.6, 0.75, 0.85],
                    "n_bootstraps": 1000,
                },
                "sharpe_ci_low": 0.42,
                "sharpe_ci_high": 1.13,
                "permutation": {
                    "observed": 0.78,
                    "null_samples": [0.0, 0.1, -0.1, 0.05],
                },
                "permutation_p_value": 0.018,
                "regime_stratified": {
                    "RISK_ON": {"sharpe": 1.0, "n_trades": 50},
                    "RISK_OFF": {"sharpe": -0.2, "n_trades": 30},
                    "regime_concentration_warning": True,
                },
                "psr": 0.92,
                "min_trl": 24.0,
                "sr_star": 0.5,
            },
            {"variant": "other", "gate_status": "green"},
        ],
    }


# ── find_variant ────────────────────────────────────────────────────


def test_find_variant_returns_match() -> None:
    found = find_variant(_payload(), "smc_breaker_btc")
    assert found is not None
    assert found["gate_status"] == "amber"


def test_find_variant_returns_none_when_missing() -> None:
    assert find_variant(_payload(), "nope") is None


def test_find_variant_handles_none_payload() -> None:
    assert find_variant(None, "x") is None


def test_find_variant_handles_no_variants_key() -> None:
    assert find_variant({}, "x") is None


# ── build_detail ────────────────────────────────────────────────────


def test_build_detail_not_found_status() -> None:
    out = build_detail(_payload(), "missing_variant")
    assert out == {"status": "not_found", "variant": "missing_variant"}


def test_build_detail_full_payload_all_blocks_available() -> None:
    out = build_detail(_payload(), "smc_breaker_btc")
    assert out["status"] == "ok"
    assert out["gate_status"] == "amber"
    assert out["walk_forward"]["available"] is True
    assert out["walk_forward"]["n_folds"] == 3
    assert out["walk_forward"]["mode"] == "rolling"
    assert out["walk_forward"]["wfe"] == 0.81
    assert out["bootstrap"]["available"] is True
    assert out["bootstrap"]["ci_low"] == 0.42
    assert out["bootstrap"]["n_bootstraps"] == 1000
    assert out["permutation"]["available"] is True
    assert out["permutation"]["p_value"] == 0.018
    assert out["regime"]["available"] is True
    assert "RISK_ON" in out["regime"]["per_regime"]
    assert out["regime"]["concentration_warning"] is True
    assert out["psr_min_trl"]["available"] is True
    assert out["psr_min_trl"]["psr"] == 0.92


def test_build_detail_missing_blocks_marked_unavailable() -> None:
    payload = {"variants": [{"variant": "v"}]}
    out = build_detail(payload, "v")
    assert out["status"] == "ok"
    assert out["walk_forward"]["available"] is False
    assert out["bootstrap"]["available"] is False
    assert out["permutation"]["available"] is False
    assert out["regime"]["available"] is False
    assert out["psr_min_trl"]["available"] is False


def test_build_detail_filters_nan_fold_sharpes() -> None:
    payload = {
        "variants": [
            {
                "variant": "v",
                "walk_forward_folds": [{"sharpe": float("nan")}, {"sharpe": 1.0}],
            },
        ],
    }
    out = build_detail(payload, "v")
    assert out["walk_forward"]["fold_sharpes"] == [1.0]


def test_build_detail_is_deterministic() -> None:
    payload = _payload()
    a = build_detail(payload, "smc_breaker_btc")
    b = build_detail(payload, "smc_breaker_btc")
    assert a == b
