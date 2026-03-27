"""Parity tests: canonical structure ↔ bridge snapshot ↔ TV pine payload.

These tests start from deterministic bar inputs and verify that the
structure families survive intact through the full pipeline:
  canonical builder → bridge ingest → layering/snapshot → pine payload

Normalization rules are explicit in tests/parity/normalization.py.
TV pipe-encoding is verified against the canonical/bridge output.
"""
from __future__ import annotations

import pytest

from scripts.explicit_structure_from_bars import build_explicit_structure_from_bars
from smc_adapters.ingest import build_structure_from_raw
from smc_adapters.pine import snapshot_to_pine_payload
from smc_core import apply_layering
from smc_core.types import SmcMeta, TimedVolumeInfo, VolumeInfo
from smc_tv_bridge.smc_api import encode_levels, encode_sweeps, encode_zones

from tests.parity.fixtures import PARITY_FIXTURES
from tests.parity.normalization import (
    bridge_bos_to_dicts,
    bridge_fvg_to_dicts,
    bridge_ob_to_dicts,
    bridge_sweep_to_dicts,
    decode_tv_bos,
    decode_tv_sweeps,
    decode_tv_zones,
    normalize_canonical_bos,
    normalize_canonical_fvg,
    normalize_canonical_ob,
    normalize_canonical_sweeps,
    strip_pine_style,
)
from tests.parity.report import run_parity_report


# ── Helpers ──────────────────────────────────────────────────────


def _default_meta(symbol: str, timeframe: str) -> SmcMeta:
    return SmcMeta(
        symbol=symbol,
        timeframe=timeframe,
        asof_ts=1709253580.0,
        volume=TimedVolumeInfo(
            value=VolumeInfo(regime="NORMAL", thin_fraction=0.1),
            asof_ts=1709253580.0,
            stale=False,
        ),
    )


def _build_pipeline(bars, symbol: str, timeframe: str):
    """Run canonical → bridge → pine and return all intermediate outputs."""
    canonical = build_explicit_structure_from_bars(
        bars, symbol=symbol, timeframe=timeframe, structure_profile="hybrid_default",
    )
    raw_structure = {
        "bos": canonical["bos"],
        "orderblocks": canonical["orderblocks"],
        "fvg": canonical["fvg"],
        "liquidity_sweeps": canonical["liquidity_sweeps"],
    }
    bridge_structure = build_structure_from_raw(raw_structure)
    meta = _default_meta(symbol, timeframe)
    snapshot = apply_layering(bridge_structure, meta, generated_at=1709254000.0)
    pine = snapshot_to_pine_payload(snapshot)
    return canonical, bridge_structure, snapshot, pine


# ── Parametrized fixture-driven parity tests ─────────────────────

_FIXTURE_IDS = [name for name, _, _, _ in PARITY_FIXTURES]
_FIXTURE_PARAMS = [
    pytest.param(factory, symbol, tf, id=name)
    for name, factory, symbol, tf in PARITY_FIXTURES
]


class TestCanonicalToBridgeParity:
    """Canonical structure → bridge SmcStructure parity."""

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_bos_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, bridge_structure, _, _ = _build_pipeline(bars, symbol, tf)
        assert normalize_canonical_bos(canonical["bos"]) == bridge_bos_to_dicts(bridge_structure.bos)

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_orderblock_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, bridge_structure, _, _ = _build_pipeline(bars, symbol, tf)
        assert normalize_canonical_ob(canonical["orderblocks"]) == bridge_ob_to_dicts(bridge_structure.orderblocks)

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_fvg_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, bridge_structure, _, _ = _build_pipeline(bars, symbol, tf)
        assert normalize_canonical_fvg(canonical["fvg"]) == bridge_fvg_to_dicts(bridge_structure.fvg)

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_sweep_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, bridge_structure, _, _ = _build_pipeline(bars, symbol, tf)
        assert normalize_canonical_sweeps(canonical["liquidity_sweeps"]) == bridge_sweep_to_dicts(bridge_structure.liquidity_sweeps)

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_counts_match(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, bridge_structure, _, _ = _build_pipeline(bars, symbol, tf)
        assert len(canonical["bos"]) == len(bridge_structure.bos)
        assert len(canonical["orderblocks"]) == len(bridge_structure.orderblocks)
        assert len(canonical["fvg"]) == len(bridge_structure.fvg)
        assert len(canonical["liquidity_sweeps"]) == len(bridge_structure.liquidity_sweeps)


class TestBridgeToPineParity:
    """Bridge SmcSnapshot → pine payload structure parity (sans style)."""

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_bos_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        _, bridge_structure, _, pine = _build_pipeline(bars, symbol, tf)
        assert bridge_bos_to_dicts(bridge_structure.bos) == strip_pine_style(pine["bos"])

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_orderblock_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        _, bridge_structure, _, pine = _build_pipeline(bars, symbol, tf)
        assert bridge_ob_to_dicts(bridge_structure.orderblocks) == strip_pine_style(pine["orderblocks"])

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_fvg_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        _, bridge_structure, _, pine = _build_pipeline(bars, symbol, tf)
        assert bridge_fvg_to_dicts(bridge_structure.fvg) == strip_pine_style(pine["fvg"])

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_sweep_parity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        _, bridge_structure, _, pine = _build_pipeline(bars, symbol, tf)
        assert bridge_sweep_to_dicts(bridge_structure.liquidity_sweeps) == strip_pine_style(pine["liquidity_sweeps"])

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_pine_has_style_for_every_entity(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        _, _, _, pine = _build_pipeline(bars, symbol, tf)
        for section in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
            for entry in pine[section]:
                assert "style" in entry, f"missing style in pine {section} entry {entry.get('id')}"

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_pine_coverage_consistent(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        _, bridge_structure, _, pine = _build_pipeline(bars, symbol, tf)
        cov = pine["structure_coverage"]
        assert cov["has_bos"] == bool(bridge_structure.bos)
        assert cov["has_orderblocks"] == bool(bridge_structure.orderblocks)
        assert cov["has_fvg"] == bool(bridge_structure.fvg)
        assert cov["has_liquidity_sweeps"] == bool(bridge_structure.liquidity_sweeps)


class TestTvEncodingParity:
    """Verify that pipe-encoded /smc_tv strings reflect the canonical structure."""

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_encoded_bos_matches_canonical(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, _, _, _ = _build_pipeline(bars, symbol, tf)
        # Build bridge-style snapshot entries for BOS (as /smc_snapshot would)
        bos_entries = [
            {"time": b["time"], "price": b["price"], "dir": b["dir"]}
            for b in canonical["bos"]
        ]
        if not bos_entries:
            assert encode_levels(bos_entries) == ""
            return
        encoded = encode_levels(bos_entries)
        decoded = decode_tv_bos(encoded)
        source_sorted = sorted(bos_entries, key=lambda x: x["time"])
        assert decoded == source_sorted

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_encoded_ob_matches_canonical(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, _, _, _ = _build_pipeline(bars, symbol, tf)
        ob_entries = [
            {"low": o["low"], "high": o["high"], "dir": o["dir"], "valid": o["valid"]}
            for o in canonical["orderblocks"]
        ]
        if not ob_entries:
            assert encode_zones(ob_entries) == ""
            return
        encoded = encode_zones(ob_entries)
        decoded = decode_tv_zones(encoded)
        source_sorted = sorted(ob_entries, key=lambda x: (x["low"], x["high"]))
        assert decoded == source_sorted

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_encoded_fvg_matches_canonical(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, _, _, _ = _build_pipeline(bars, symbol, tf)
        fvg_entries = [
            {"low": f["low"], "high": f["high"], "dir": f["dir"], "valid": f["valid"]}
            for f in canonical["fvg"]
        ]
        if not fvg_entries:
            assert encode_zones(fvg_entries) == ""
            return
        encoded = encode_zones(fvg_entries)
        decoded = decode_tv_zones(encoded)
        source_sorted = sorted(fvg_entries, key=lambda x: (x["low"], x["high"]))
        assert decoded == source_sorted

    @pytest.mark.parametrize("factory,symbol,tf", _FIXTURE_PARAMS)
    def test_encoded_sweeps_matches_canonical(self, factory, symbol, tf) -> None:
        bars = factory(symbol=symbol)
        canonical, _, _, _ = _build_pipeline(bars, symbol, tf)
        sweep_entries = [
            {"time": s["time"], "price": s["price"], "side": s["side"]}
            for s in canonical["liquidity_sweeps"]
        ]
        if not sweep_entries:
            assert encode_sweeps(sweep_entries) == ""
            return
        encoded = encode_sweeps(sweep_entries)
        decoded = decode_tv_sweeps(encoded)
        source_sorted = sorted(sweep_entries, key=lambda x: x["time"])
        assert decoded == source_sorted


# ── Parity report integration ────────────────────────────────────


def test_parity_report_all_pass():
    """Run the full parity report and assert no drift is detected."""
    results = run_parity_report()
    for r in results:
        assert r.error is None, f"fixture {r.name}: {r.error}"
        for fam in r.families:
            assert fam.normalized_match, f"fixture {r.name} canonical→bridge {fam.family}: drift detected"
        for fam in r.pine_families:
            assert fam.normalized_match, f"fixture {r.name} bridge→pine {fam.family}: drift detected"
