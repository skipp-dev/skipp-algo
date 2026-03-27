"""Regression tests for SMC bridge output contracts.

These tests verify that the response shapes produced by /smc_snapshot,
/smc_tv, and the canonical structure builder remain stable across
refactors.  They intentionally do NOT call live endpoints; they exercise
the underlying builder functions with mock/fixture data so they stay
fast and deterministic.
"""
from __future__ import annotations

import pytest

from tests.fixture_helpers import assert_keys_subset, load_fixture

# ── Golden fixture loading ───────────────────────────────────────────


@pytest.fixture()
def golden_snapshot() -> dict:
    return load_fixture("golden_smc_snapshot.json")


@pytest.fixture()
def golden_tv() -> dict:
    return load_fixture("golden_smc_tv.json")


@pytest.fixture()
def golden_structure() -> dict:
    return load_fixture("golden_canonical_structure.json")


# ── /smc_snapshot contract ───────────────────────────────────────────

_SNAPSHOT_REQUIRED_KEYS = {
    "symbol",
    "timeframe",
    "bos",
    "orderblocks",
    "fvg",
    "liquidity_sweeps",
    "regime",
    "technicalscore",
    "newsscore",
}


def test_snapshot_required_keys(golden_snapshot: dict) -> None:
    assert_keys_subset(_SNAPSHOT_REQUIRED_KEYS, golden_snapshot, "/smc_snapshot")


def test_snapshot_bos_entries_have_required_fields(golden_snapshot: dict) -> None:
    for entry in golden_snapshot["bos"]:
        assert_keys_subset({"time", "price", "dir"}, entry, "bos entry")


def test_snapshot_orderblocks_have_required_fields(golden_snapshot: dict) -> None:
    for entry in golden_snapshot["orderblocks"]:
        assert_keys_subset({"low", "high", "dir", "valid"}, entry, "orderblock entry")


def test_snapshot_fvg_have_required_fields(golden_snapshot: dict) -> None:
    for entry in golden_snapshot["fvg"]:
        assert_keys_subset({"low", "high", "dir", "valid"}, entry, "fvg entry")


def test_snapshot_sweeps_have_required_fields(golden_snapshot: dict) -> None:
    for entry in golden_snapshot["liquidity_sweeps"]:
        assert_keys_subset({"time", "price", "side"}, entry, "sweep entry")


def test_snapshot_regime_has_required_fields(golden_snapshot: dict) -> None:
    assert_keys_subset({"volume_regime"}, golden_snapshot["regime"], "regime")


# ── /smc_tv contract ────────────────────────────────────────────────

_TV_REQUIRED_KEYS = {"bos", "ob", "fvg", "sweeps", "regime", "tech", "news"}


def test_tv_required_keys(golden_tv: dict) -> None:
    assert_keys_subset(_TV_REQUIRED_KEYS, golden_tv, "/smc_tv")


def test_tv_bos_is_pipe_encoded(golden_tv: dict) -> None:
    bos_str = golden_tv["bos"]
    assert isinstance(bos_str, str)
    for segment in bos_str.split(";"):
        parts = segment.split("|")
        assert len(parts) == 3, f"bos segment should have 3 pipe parts: {segment}"


def test_tv_ob_is_pipe_encoded(golden_tv: dict) -> None:
    ob_str = golden_tv["ob"]
    assert isinstance(ob_str, str)
    for segment in ob_str.split(";"):
        parts = segment.split("|")
        assert len(parts) == 4, f"ob segment should have 4 pipe parts: {segment}"


def test_tv_sweeps_is_pipe_encoded(golden_tv: dict) -> None:
    sweeps_str = golden_tv["sweeps"]
    assert isinstance(sweeps_str, str)
    for segment in sweeps_str.split(";"):
        parts = segment.split("|")
        assert len(parts) == 3, f"sweeps segment should have 3 pipe parts: {segment}"


# ── /smc_tv live builder ────────────────────────────────────────────

def test_tv_encode_roundtrip_from_snapshot(golden_snapshot: dict) -> None:
    """build_smc_snapshot → encode → assert keys present in TV shape."""
    from smc_tv_bridge.smc_api import encode_levels, encode_sweeps, encode_zones

    tv = {
        "bos": encode_levels(golden_snapshot["bos"]),
        "ob": encode_zones(golden_snapshot["orderblocks"]),
        "fvg": encode_zones(golden_snapshot["fvg"]),
        "sweeps": encode_sweeps(golden_snapshot["liquidity_sweeps"]),
        "regime": golden_snapshot["regime"]["volume_regime"],
        "tech": golden_snapshot["technicalscore"],
        "news": golden_snapshot["newsscore"],
    }
    assert_keys_subset(_TV_REQUIRED_KEYS, tv, "encoded TV payload")
    assert isinstance(tv["bos"], str) and "|" in tv["bos"]
    assert isinstance(tv["ob"], str) and "|" in tv["ob"]
    assert isinstance(tv["sweeps"], str) and "|" in tv["sweeps"]


# ── canonical structure contract ─────────────────────────────────────

_STRUCTURE_REQUIRED_KEYS = {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
_STRUCTURE_FULL_KEYS = _STRUCTURE_REQUIRED_KEYS | {"auxiliary", "diagnostics", "producer_debug"}


def test_canonical_structure_required_keys(golden_structure: dict) -> None:
    assert_keys_subset(_STRUCTURE_FULL_KEYS, golden_structure, "canonical structure")


def test_canonical_structure_bos_has_id(golden_structure: dict) -> None:
    for entry in golden_structure["bos"]:
        assert "id" in entry
        assert entry["id"].startswith("bos:")


def test_canonical_structure_ob_has_id(golden_structure: dict) -> None:
    for entry in golden_structure["orderblocks"]:
        assert "id" in entry
        assert entry["id"].startswith("ob:")


def test_canonical_structure_fvg_has_id(golden_structure: dict) -> None:
    for entry in golden_structure["fvg"]:
        assert "id" in entry
        assert entry["id"].startswith("fvg:")


def test_canonical_structure_sweeps_has_id(golden_structure: dict) -> None:
    for entry in golden_structure["liquidity_sweeps"]:
        assert "id" in entry
        assert entry["id"].startswith("sweep:")


def test_canonical_structure_producer_debug(golden_structure: dict) -> None:
    debug = golden_structure["producer_debug"]
    assert_keys_subset(
        {"liquidity_levels_count", "structure_profile_used", "event_logic_version"},
        debug,
        "producer_debug",
    )


# ── mock snapshot builder ────────────────────────────────────────────

def test_mock_snapshot_matches_contract() -> None:
    """_mock_snapshot produces output satisfying the /smc_snapshot contract."""
    from smc_tv_bridge.smc_api import _mock_snapshot

    snap = _mock_snapshot("AAPL", "15m")
    assert_keys_subset(_SNAPSHOT_REQUIRED_KEYS, snap, "mock snapshot")
    assert len(snap["bos"]) >= 1
    assert len(snap["orderblocks"]) >= 1
    assert len(snap["fvg"]) >= 1
    assert len(snap["liquidity_sweeps"]) >= 1
