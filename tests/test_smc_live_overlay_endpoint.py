"""Tests for GET /smc_live (smc-live-overlay/1 endpoint, WP-B).

Validates the flat live-overlay payload served at ``/smc_live``:
  - schema conformance against ``spec/smc_live_overlay.schema.json``
  - envelope correctness (schema id, uppercased symbol, tf, asof_ts, stale)
  - news bias/strength mapping from the (signed) news score, incl. deadband
    and [0, 1] clamping
  - omission of baked-only fields (``flow_rel_vol`` / ``squeeze_on``) so the
    Pine side falls back to its baked ``mp.*`` defaults
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

# Fields the endpoint must NOT serve (baked-only); their absence is what lets
# Pine keep its baked mp.* defaults. ``tone`` (WP-G), ``vix_level`` (WP-H), the
# flow-delta/ATS fields (WP-K) and the event-risk fields (WP-B2) are served, so
# they are intentionally absent from this list.
_BAKED_ONLY_KEYS = (
    "flow_rel_vol",
    "squeeze_on",
)


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _stub_event_risk_resolver() -> object:
    """Keep /smc_live tests hermetic w.r.t. the event-risk resolver (WP-B2).

    ``_get_event_risk`` is wired into every payload build. Under ``USE_MOCK`` it
    returns canned fields; otherwise it resolves from the cached Databento
    reference snapshot (no earnings/calendar/news feed is wired here yet). Default
    every test to a no-data resolve (-> no event fields, Pine keeps its baked
    posture) over a clean cache so the suite stays network-free and
    order-independent. Event-specific tests re-patch as needed.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "_fetch_event_risk_uncached", lambda symbol: {})
        mp.setattr(smc_api, "_event_cache", {})
        mp.setattr(smc_api, "_event_symbol_locks", {})
        yield


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
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)
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
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)
        result = smc_api.smc_live_endpoint(symbol="zzzz", tf="15m")

    jsonschema.validate(result, _schema())
    assert "news_strength" not in result
    assert "news_bias" not in result
    assert "tone" not in result
    assert "vix_level" not in result
    assert "flow_delta_proxy_pct" not in result
    assert "ats_state" not in result
    assert "ats_zscore" not in result
    for key in (
        "event_window_state",
        "event_risk_level",
        "next_event_name",
        "next_event_time",
        "market_event_blocked",
        "symbol_event_blocked",
        "event_provider_status",
    ):
        assert key not in result
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
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)
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
        mp.setattr(smc_api, "_vix_cache", {"value": None, "fetched_at": 0.0})
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)
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
        mp.setattr(smc_api, "_vix_cache", {"value": None, "fetched_at": 0.0})
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)

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


def test_smc_live_flow_ats_mock_wiring() -> None:
    """Mock wiring serves the flow-delta + ATS fields (B2, WP-K)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", True)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert result["flow_delta_proxy_pct"] == pytest.approx(
        smc_api._FLOW_MOCK_FIELDS["flow_delta_proxy_pct"]
    )
    assert result["ats_zscore"] == pytest.approx(smc_api._FLOW_MOCK_FIELDS["ats_zscore"])
    assert result["ats_state"] == smc_api._FLOW_MOCK_FIELDS["ats_state"]


def test_smc_live_flow_ats_fetch_miss_omits_fields() -> None:
    """A flow/ATS miss omits all three fields -> Pine keeps its baked mp.*.

    Serving fabricated values would override the baked fallback with non-data;
    the safety invariant requires omitting the fields instead (never loosen).
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        mp.setattr(smc_api, "_fetch_flow_ats_uncached", lambda s: None)
        mp.setattr(smc_api, "_flow_cache", {})
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert "flow_delta_proxy_pct" not in result
    assert "ats_state" not in result
    assert "ats_zscore" not in result


def test_smc_live_flow_ats_empty_window_omits_fields() -> None:
    """An empty trade window (n_trades == 0) omits all three flow/ATS fields.

    ``fetch_symbol_microstructure`` returns neutral defaults
    (``avg_trade_size=0.0`` / ``buy_volume_pct=50.0``) when there are no trades
    (e.g. outside market hours), so a None-only guard would still emit a
    fabricated overlay. ``_fetch_flow_ats_uncached`` must fail closed on
    ``n_trades == 0`` so Pine keeps its baked ``mp.*`` baseline (never loosen).
    """

    def _empty_window(*_args: object, **_kwargs: object) -> dict[str, float]:
        return {
            "buy_volume_pct": 50.0,
            "avg_trade_size": 0.0,
            "total_size": 0,
            "n_trades": 0,
            "buy_size": 0,
            "sell_size": 0,
        }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        mp.setattr(
            smc_api,
            "_load_ats_baseline_symbols",
            lambda: {
                "AAPL": {
                    smc_api._ATS_MEAN_KEY: 100.0,
                    smc_api._ATS_STD_KEY: 20.0,
                }
            },
        )
        mp.setattr(smc_api, "_flow_cache", {})
        mp.setattr(smc_api, "_flow_symbol_locks", {})
        # The fetcher is lazily imported inside _fetch_flow_ats_uncached, so
        # patch it on its source module rather than on smc_api.
        mp.setattr(
            "scripts.smc_trades_microstructure.fetch_symbol_microstructure",
            _empty_window,
        )
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert "flow_delta_proxy_pct" not in result
    assert "ats_state" not in result
    assert "ats_zscore" not in result


def test_smc_live_flow_ats_cache_coalesces_concurrent_fetches() -> None:
    """A cold/expired cache triggers exactly one flow/ATS fetch per symbol.

    Per-symbol flow/ATS values are cached under a per-symbol lock, so 32
    concurrent callers for the same symbol must coalesce into a single
    ``_fetch_flow_ats_uncached`` call and all observe the same fields. Guards
    the shared-mutable cache against lost/duplicated fetches.
    """
    calls: list[int] = []
    calls_lock = threading.Lock()

    def _counting_fetch(symbol: str) -> dict[str, float | str]:
        with calls_lock:
            calls.append(1)
        return {"flow_delta_proxy_pct": 5.0, "ats_zscore": 1.0, "ats_state": "SPIKE_UP"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        mp.setattr(smc_api, "_fetch_flow_ats_uncached", _counting_fetch)
        mp.setattr(smc_api, "_flow_cache", {})
        mp.setattr(smc_api, "_flow_symbol_locks", {})

        n_threads = 32
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            results = list(
                pool.map(
                    lambda _: smc_api.smc_live_endpoint(symbol="aapl", tf="15m"),
                    range(n_threads),
                )
            )

    assert len(calls) == 1, f"expected a single coalesced fetch, got {len(calls)}"
    assert {r["flow_delta_proxy_pct"] for r in results} == {5.0}
    assert {r["ats_state"] for r in results} == {"SPIKE_UP"}


def test_smc_live_event_risk_mock_wiring() -> None:
    """Mock wiring serves the event-risk overlay fields (B2, WP-B2)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", True)
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    assert result["event_window_state"] == smc_api._EVENT_MOCK_FIELDS["event_window_state"]
    assert result["event_risk_level"] == smc_api._EVENT_MOCK_FIELDS["event_risk_level"]
    assert result["next_event_name"] == smc_api._EVENT_MOCK_FIELDS["next_event_name"]
    assert result["next_event_time"] == smc_api._EVENT_MOCK_FIELDS["next_event_time"]
    assert result["symbol_event_blocked"] is True
    assert result["event_provider_status"] == "ok"
    # The mock omits market_event_blocked -> tighten-only (no False emitted).
    assert "market_event_blocked" not in result


def test_smc_live_event_risk_no_data_omits_fields() -> None:
    """A no-data event resolve omits every event field -> Pine keeps mp.* posture.

    Serving fabricated event state would override the baked posture with
    non-data; the safety invariant requires omitting the fields instead so the
    overlay can only tighten, never loosen, the baked gating.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)
        mp.setattr(smc_api, "_fetch_event_risk_uncached", lambda s: {})
        mp.setattr(smc_api, "_event_cache", {})
        result = smc_api.smc_live_endpoint(symbol="aapl", tf="15m")

    jsonschema.validate(result, _schema())
    for key in (
        "event_window_state",
        "event_risk_level",
        "next_event_name",
        "next_event_time",
        "market_event_blocked",
        "symbol_event_blocked",
        "event_provider_status",
    ):
        assert key not in result, f"event field {key!r} must be omitted on no-data"


def test_event_light_to_overlay_fields_blocks_are_tighten_only() -> None:
    """The mapping emits block flags only when True and drops no-data entirely.

    Safety invariant: the overlay may assert a block (True) but must never emit
    a False that could lift the baked block on the Pine side. A ``no_data``
    provider status drops every field so Pine keeps its baked posture.
    """
    # no_data -> everything omitted.
    assert smc_api._event_light_to_overlay_fields({"EVENT_PROVIDER_STATUS": "no_data"}) == {}

    # False block flags are dropped; True is emitted.
    mapped = smc_api._event_light_to_overlay_fields(
        {
            "EVENT_WINDOW_STATE": "PRE_EVENT",
            "EVENT_RISK_LEVEL": "HIGH",
            "NEXT_EVENT_NAME": "AAPL Q3 Earnings",
            "NEXT_EVENT_TIME": "14:00",
            "MARKET_EVENT_BLOCKED": False,
            "SYMBOL_EVENT_BLOCKED": True,
            "EVENT_PROVIDER_STATUS": "ok",
        }
    )
    assert mapped["event_window_state"] == "PRE_EVENT"
    assert mapped["event_risk_level"] == "HIGH"
    assert mapped["next_event_name"] == "AAPL Q3 Earnings"
    assert mapped["next_event_time"] == "14:00"
    assert "market_event_blocked" not in mapped  # False must never be emitted
    assert mapped["symbol_event_blocked"] is True
    assert mapped["event_provider_status"] == "ok"

    # Empty optional strings are dropped; a clean provider status still serves.
    sparse = smc_api._event_light_to_overlay_fields(
        {
            "EVENT_WINDOW_STATE": "CLEAR",
            "EVENT_RISK_LEVEL": "NONE",
            "NEXT_EVENT_NAME": "",
            "NEXT_EVENT_TIME": "",
            "MARKET_EVENT_BLOCKED": False,
            "SYMBOL_EVENT_BLOCKED": False,
            "EVENT_PROVIDER_STATUS": "ok",
        }
    )
    assert sparse == {
        "event_window_state": "CLEAR",
        "event_risk_level": "NONE",
        "event_provider_status": "ok",
    }


def test_smc_live_event_risk_cache_coalesces_concurrent_fetches() -> None:
    """A cold/expired cache triggers exactly one event-risk fetch per symbol.

    Per-symbol event-risk fields are cached under a per-symbol lock, so 32
    concurrent callers for the same symbol must coalesce into a single
    ``_fetch_event_risk_uncached`` call and all observe the same fields. Guards
    the shared-mutable cache against lost/duplicated fetches.
    """
    calls: list[int] = []
    calls_lock = threading.Lock()

    def _counting_fetch(symbol: str) -> dict[str, object]:
        with calls_lock:
            calls.append(1)
        return {
            "event_window_state": "ACTIVE",
            "event_risk_level": "HIGH",
            "event_provider_status": "ok",
        }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(smc_api, "USE_MOCK", False)
        mp.setattr(smc_api, "build_smc_snapshot", lambda symbol, tf: {"newsscore": 0.0})
        mp.setattr(smc_api, "_get_vix_level", lambda: None)
        mp.setattr(smc_api, "_get_flow_ats_fields", lambda s: None)
        mp.setattr(smc_api, "_fetch_event_risk_uncached", _counting_fetch)
        mp.setattr(smc_api, "_event_cache", {})
        mp.setattr(smc_api, "_event_symbol_locks", {})

        n_threads = 32
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            results = list(
                pool.map(
                    lambda _: smc_api.smc_live_endpoint(symbol="aapl", tf="15m"),
                    range(n_threads),
                )
            )

    assert len(calls) == 1, f"expected a single coalesced fetch, got {len(calls)}"
    assert {r["event_window_state"] for r in results} == {"ACTIVE"}
    assert {r["event_risk_level"] for r in results} == {"HIGH"}
