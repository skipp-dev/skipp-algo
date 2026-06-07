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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest

import smc_tv_bridge.smc_api as smc_api

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "spec" / "smc_live_overlay.schema.json"

# Fields the endpoint must NOT serve (baked-only or not-yet-populated B2);
# their absence is what lets Pine keep its baked mp.* defaults. ``tone`` (WP-G)
# and ``vix_level`` (WP-H) are served, so they are intentionally absent here.
_BAKED_ONLY_KEYS = (
    "flow_rel_vol",
    "squeeze_on",
    "flow_delta_proxy_pct",
    "ats_state",
    "ats_zscore",
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
    assert result["vix_level"] > 0.0


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
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert result["news_bias"] == expected_bias
    assert result["news_strength"] == pytest.approx(expected_strength)


def test_smc_live_off_universe_emits_envelope_only() -> None:
    """A 0.0 score (off-universe / no data) omits news fields -> Pine keeps mp.*.

    Emitting a fabricated ``news_strength: 0.0`` would override a real baked
    news signal on the Pine side, loosening a gating condition with non-data;
    the safety invariant requires degrading to the envelope only instead. With
    no technical score either (defaulting to the neutral 0.5), ``tone`` is also
    omitted so Pine keeps its baked ``mp.tone``.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        result = smc_api.smc_live_endpoint(symbol="zzzz", tf="15m")

    jsonschema.validate(result, _schema())
    assert "news_strength" not in result
    assert "news_bias" not in result
    assert "tone" not in result
    assert "vix_level" not in result
    # Envelope is still complete and valid.
    assert result["schema"] == "smc-live-overlay/1"
    assert result["symbol"] == "ZZZZ"
    assert result["tf"] == "15m"
    assert isinstance(result["asof_ts"], int)
    assert result["stale"] is False


def test_smc_live_tone_mock_wiring() -> None:
    """Mock wiring serves a canonical ``tone`` (B2, WP-G).

    The mock snapshot (technical score 0.68 BULLISH, news score +0.42) yields a
    bullish global heat, so the layering tone is ``BULLISH``. The tone is
    derived through the same ``compute_library_layering`` function that bakes
    ``mp.tone``, so the live overlay shares the baseline's weighting/thresholds.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", True)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert result["tone"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert result["tone"] == "BULLISH"


def test_smc_live_tone_matches_canonical_layering() -> None:
    """The served tone equals ``compute_library_layering`` for the same inputs.

    Guards against drift between the endpoint's tone mapping and the canonical
    baking path: both must agree field-for-field on identical scores.
    """
    from scripts.smc_library_layering import compute_library_layering

    snap = {
        "newsscore": -0.30,
        "technicalscore": 0.20,
        "technicalsignal": "BEARISH",
        "regime": {"volume_regime": "NORMAL"},
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: snap)
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    expected = compute_library_layering(
        news="BEARISH",
        technical_strength=min(1.0, abs(0.20 - 0.5) * 2.0),
        technical_bias="BEARISH",
        volume_regime="NORMAL",
    )
    jsonschema.validate(result, _schema())
    assert result["tone"] == expected["tone"]
    assert result["tone"] == "BEARISH"


def test_smc_live_unsupported_timeframe() -> None:
    """A bad timeframe mirrors the /smc_tv error contract (no payload built)."""
    result = smc_api.smc_live_endpoint(symbol="aapl", tf="42m")
    assert result == {"error": "unsupported timeframe: 42m"}


def test_smc_live_vix_mock_wiring() -> None:
    """Mock wiring serves the market-wide VIX level (B2, WP-H)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", True)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert result["vix_level"] == pytest.approx(smc_api._VIX_MOCK_LEVEL)
    assert result["vix_level"] > 0.0


def test_smc_live_vix_fetch_miss_omits_field() -> None:
    """A VIX fetch miss omits ``vix_level`` -> Pine keeps its baked mp.vix.

    Serving a fabricated level would override the baked fallback with non-data;
    the safety invariant requires omitting the field instead (never loosen).
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_fetch_vix_uncached", lambda: None)
        smc_api._vix_cache.update({"value": None, "fetched_at": 0.0})
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert "vix_level" not in result


def test_smc_live_vix_cache_coalesces_concurrent_fetches() -> None:
    """A cold/expired cache triggers exactly one upstream VIX fetch under load.

    VIX is market-wide and cached under a lock, so 32 concurrent callers must
    coalesce into a single ``_fetch_vix_uncached`` call and all observe the
    same level. Guards the shared-mutable cache against lost/duplicated fetches.
    """
    calls: list[int] = []
    calls_lock = threading.Lock()

    def _counting_fetch() -> float:
        with calls_lock:
            calls.append(1)
        return 21.0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_fetch_vix_uncached", _counting_fetch)
        smc_api._vix_cache.update({"value": None, "fetched_at": 0.0})

        n_threads = 32
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            results = list(
                pool.map(
                    lambda _: smc_api.smc_live_endpoint(symbol="aapl", tf="15m"),
                    range(n_threads),
                )
            )

    assert len(calls) == 1, f"expected a single coalesced fetch, got {len(calls)}"
    assert {r["vix_level"] for r in results} == {21.0}
