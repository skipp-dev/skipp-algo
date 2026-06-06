"""Tests for GET /smc_live (smc-live-overlay/1 endpoint, WP-B).

Validates the flat live-overlay payload served at ``/smc_live``:
  - schema conformance against ``spec/smc_live_overlay.schema.json``
  - envelope correctness (schema id, uppercased symbol, tf, asof_ts, stale)
  - news bias/strength mapping from the (signed) news score, incl. deadband
    and [0, 1] clamping
  - omission of baked-only fields (``flow_rel_vol`` / ``squeeze_on`` / B2) so
    the Pine side falls back to its baked ``mp.*`` defaults
  - unsupported-timeframe error mirrors the existing ``/smc_tv`` contract

Endpoint functions are invoked directly (repo convention — no TestClient),
keeping the tests network-free and deterministic.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import jsonschema
import pytest

import smc_tv_bridge.smc_api as smc_api

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "spec" / "smc_live_overlay.schema.json"

# Fields the Phase-1 endpoint must NOT serve (baked-only or B2 forward-compat);
# their absence is what lets Pine keep its baked mp.* defaults.
_BAKED_ONLY_KEYS = (
    "flow_rel_vol",
    "squeeze_on",
    "vix_level",
    "flow_delta_proxy_pct",
    "ats_state",
    "ats_zscore",
    "tone",
)


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_smc_live_schema_conformant_mock_wiring() -> None:
    """End-to-end mock wiring: the payload validates against the JSON schema."""
    before = int(time.time())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", True)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")
    after = int(time.time())

    jsonschema.validate(result, _schema())

    assert result["schema"] == "smc-live-overlay/1"
    assert result["symbol"] == "AAPL"  # symbol is uppercased
    assert result["tf"] == "15m"
    assert isinstance(result["asof_ts"], int)
    assert before <= result["asof_ts"] <= after
    assert result["stale"] is False
    assert 0.0 <= result["news_strength"] <= 1.0
    assert result["news_bias"] in {"BULLISH", "BEARISH", "NEUTRAL"}


def test_smc_live_omits_baked_only_fields() -> None:
    """Phase-1 serves news fields only; baked-only keys must be absent."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", True)
        result = smc_api.smc_live_endpoint(symbol="nvda", tf="1H")
    for key in _BAKED_ONLY_KEYS:
        assert key not in result, f"baked-only field {key!r} must be omitted"


@pytest.mark.parametrize(
    ("score", "expected_bias", "expected_strength"),
    [
        (0.42, "BULLISH", 0.42),
        (-0.42, "BEARISH", 0.42),
        (0.03, "NEUTRAL", 0.03),   # nonzero but within deadband -> neutral bias
        (-0.03, "NEUTRAL", 0.03),  # nonzero but within deadband -> neutral bias
        (1.5, "BULLISH", 1.0),     # strength clamped to [0, 1]
        (-2.0, "BEARISH", 1.0),    # strength clamped to [0, 1]
    ],
)
def test_smc_live_bias_mapping(score: float, expected_bias: str, expected_strength: float) -> None:
    """News bias/strength derive deterministically from the signed score."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": score})
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert result["news_bias"] == expected_bias
    assert result["news_strength"] == pytest.approx(expected_strength)


def test_smc_live_off_universe_emits_envelope_only() -> None:
    """A 0.0 score (off-universe / no data) omits news fields -> Pine keeps mp.*.

    Emitting a fabricated ``news_strength: 0.0`` would override a real baked
    news signal on the Pine side, loosening a gating condition with non-data;
    the safety invariant requires degrading to the envelope only instead.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        result = smc_api.smc_live_endpoint(symbol="zzzz", tf="15m")

    jsonschema.validate(result, _schema())
    assert "news_strength" not in result
    assert "news_bias" not in result
    # Envelope is still complete and valid.
    assert result["schema"] == "smc-live-overlay/1"
    assert result["symbol"] == "ZZZZ"
    assert result["tf"] == "15m"
    assert isinstance(result["asof_ts"], int)
    assert result["stale"] is False


def test_smc_live_unsupported_timeframe() -> None:
    """A bad timeframe mirrors the /smc_tv error contract (no payload built)."""
    result = smc_api.smc_live_endpoint(symbol="aapl", tf="42m")
    assert result == {"error": "unsupported timeframe: 42m"}
