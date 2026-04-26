"""Tests for ``scripts.build_dashboard_payload`` (C7/T2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.build_dashboard_payload import (
    DASHBOARD_PAYLOAD_VERSION,
    build_dashboard_payload,
)


_FROZEN_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _seed_minimal_cache(cache_dir: Path, date: str = "2026-04-26") -> None:
    """Write a minimum coherent set of sprint outputs for one variant."""
    variant_key = {"setup_type": "smc_breaker", "symbol_group": "btc"}
    _write(
        cache_dir / f"walk_forward_{date}.json",
        {
            "variants": [
                {
                    **variant_key,
                    "regime": "RISK_ON",
                    "n_trades": 142,
                    "hit_rate": 0.58,
                    "sharpe": 0.93,
                    "wfe": 0.62,
                    "max_dd": 0.094,
                }
            ]
        },
    )
    _write(
        cache_dir / f"bootstrap_ci_{date}.json",
        {
            "variants": [
                {**variant_key, "sharpe_ci_low": 0.42, "sharpe_ci_high": 1.31}
            ]
        },
    )
    _write(
        cache_dir / f"permutation_{date}.json",
        {"variants": [{**variant_key, "p_value": 0.018, "bh_fdr_pass": True}]},
    )
    _write(
        cache_dir / f"regime_stratified_{date}.json",
        {"variants": [{**variant_key, "regime_concentration": 0.71}]},
    )
    _write(
        cache_dir / f"psr_mintrl_{date}.json",
        {"variants": [{**variant_key, "psr_at_0": 0.91, "min_trl_at_0": 168}]},
    )


def test_returns_empty_payload_when_cache_dir_is_empty(tmp_path: Path) -> None:
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    assert payload["version"] == DASHBOARD_PAYLOAD_VERSION
    assert payload["as_of_date"] is None
    assert payload["variants"] == []
    assert payload["global"]["total_variants"] == 0
    assert any("no walk_forward_" in w for w in payload["warnings"])


def test_picks_newest_walk_forward_date_when_unspecified(tmp_path: Path) -> None:
    _seed_minimal_cache(tmp_path, date="2026-04-25")
    _seed_minimal_cache(tmp_path, date="2026-04-26")
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    assert payload["as_of_date"] == "2026-04-26"


def test_joins_all_sprints_into_one_variant_row(tmp_path: Path) -> None:
    _seed_minimal_cache(tmp_path)
    gate = {"status": "yellow", "n_trades": 142, "checks": [], "summary": {}}
    payload = build_dashboard_payload(
        tmp_path, track_record_gate=gate, now=_FROZEN_NOW
    )
    assert len(payload["variants"]) == 1
    v = payload["variants"][0]
    assert v["setup_type"] == "smc_breaker"
    assert v["symbol_group"] == "btc"
    assert v["bootstrap_ci_low"] == pytest.approx(0.42)
    assert v["bootstrap_ci_high"] == pytest.approx(1.31)
    assert v["perm_p"] == pytest.approx(0.018)
    assert v["bh_fdr_pass"] is True
    assert v["psr_at_0"] == pytest.approx(0.91)
    assert v["min_trl_at_0"] == 168
    assert v["regime_concentration"] == pytest.approx(0.71)
    # yellow gate verdict surfaces as "amber" in the dashboard vocab.
    assert v["gate_status"] == "amber"


def test_missing_sidecar_files_fall_back_to_none(tmp_path: Path) -> None:
    # Only walk-forward present — every other artefact missing.
    date = "2026-04-26"
    _write(
        tmp_path / f"walk_forward_{date}.json",
        {
            "variants": [
                {
                    "setup_type": "smc_breaker",
                    "symbol_group": "btc",
                    "regime": "RISK_ON",
                    "n_trades": 100,
                }
            ]
        },
    )
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    v = payload["variants"][0]
    assert v["bootstrap_ci_low"] is None
    assert v["bootstrap_ci_high"] is None
    assert v["perm_p"] is None
    assert v["psr_at_0"] is None
    assert v["min_trl_at_0"] is None
    assert v["regime_concentration"] is None
    # bh_fdr_pass defaults to False when permutation is absent.
    assert v["bh_fdr_pass"] is False
    # gate_status is "unknown" when no track-record-gate verdict is loaded.
    assert v["gate_status"] == "unknown"
    assert any("permutation" in w for w in payload["warnings"])


def test_global_counts_aggregate_per_status(tmp_path: Path) -> None:
    date = "2026-04-26"
    _write(
        tmp_path / f"walk_forward_{date}.json",
        {
            "variants": [
                {"setup_type": "a", "symbol_group": "x", "regime": "R", "n_trades": 1},
                {"setup_type": "b", "symbol_group": "y", "regime": "R", "n_trades": 1},
            ]
        },
    )
    payload = build_dashboard_payload(
        tmp_path,
        track_record_gate={"status": "green", "n_trades": 1, "checks": [], "summary": {}},
        now=_FROZEN_NOW,
    )
    g = payload["global"]
    assert g["total_variants"] == 2
    assert g["gate_green"] == 2
    assert g["gate_amber"] == 0
    assert g["gate_red"] == 0


def test_track_record_gate_loaded_from_disk_when_not_passed(tmp_path: Path) -> None:
    date = "2026-04-26"
    _seed_minimal_cache(tmp_path, date=date)
    _write(
        tmp_path / f"track_record_gate_{date}.json",
        {"status": "red", "n_trades": 142, "checks": [], "summary": {}},
    )
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    assert payload["variants"][0]["gate_status"] == "red"
    assert payload["global"]["gate_red"] == 1


def test_payload_is_deterministic(tmp_path: Path) -> None:
    _seed_minimal_cache(tmp_path)
    a = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    b = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_payload_is_json_serialisable(tmp_path: Path) -> None:
    _seed_minimal_cache(tmp_path)
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    # Must round-trip cleanly so the dashboard can cache it on disk.
    encoded = json.dumps(payload)
    assert json.loads(encoded) == payload


def test_variant_row_carries_consumer_aliases(tmp_path: Path) -> None:
    """C7 BLOCKER fix: producer must emit consumer-friendly aliases.

    The three Streamlit tabs (tab_track_record, tab_calibration_detail,
    tab_live_incubation) read ``variant``, ``sharpe_ci_low/high``,
    ``permutation_p_value``, ``psr``, ``walk_forward_efficiency``,
    ``max_drawdown``. Pin those keys so the producer/consumer drift
    that the deep-review found cannot reappear silently.
    """
    _seed_minimal_cache(tmp_path)
    payload = build_dashboard_payload(tmp_path, now=_FROZEN_NOW)
    assert payload["variants"], "expected one variant from minimal cache"
    row = payload["variants"][0]
    aliases = {
        "variant",
        "sharpe_ci_low",
        "sharpe_ci_high",
        "permutation_p_value",
        "psr",
        "walk_forward_efficiency",
        "max_drawdown",
    }
    missing = aliases - set(row)
    assert not missing, f"missing C7 consumer aliases: {missing}"
    # Aliases must equal their canonical values.
    assert row["sharpe_ci_low"] == row["bootstrap_ci_low"]
    assert row["sharpe_ci_high"] == row["bootstrap_ci_high"]
    assert row["permutation_p_value"] == row["perm_p"]
    assert row["psr"] == row["psr_at_0"]
    assert row["walk_forward_efficiency"] == row["wfe"]
    assert row["max_drawdown"] == row["max_dd"]


def test_dashboard_payload_version_is_semver() -> None:
    """C7 deep-review fix: schema_version bumped from "v1" to semver."""
    parts = DASHBOARD_PAYLOAD_VERSION.split(".")
    assert len(parts) == 3, f"expected MAJOR.MINOR.PATCH, got {DASHBOARD_PAYLOAD_VERSION}"
    for p in parts:
        assert p.isdigit(), f"non-numeric semver part: {p!r}"
