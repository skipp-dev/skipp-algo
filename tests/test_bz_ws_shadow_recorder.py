"""Unit tests for the Benzinga WS↔REST shadow-latency recorder core.

Only the *pure* join / delta / scoring logic is exercised here — the live
WS/REST threads and the Databento edge-sim are I/O shims covered elsewhere.
The design mirrors ``scripts/measure_ttf.py``: pure core, thin I/O wrapper.
"""

from __future__ import annotations

import pytest

from scripts.bz_ws_shadow_recorder import (
    ShadowJoinLedger,
    ShadowRecord,
    compute_deltas,
    quick_catalyst_score,
    record_to_dict,
)

# ── quick_catalyst_score ────────────────────────────────────────────


def test_catalyst_score_hits_known_event_keywords() -> None:
    assert quick_catalyst_score("ACME announces FDA approval for its lead drug") > 0.0
    assert quick_catalyst_score("XYZ prices $500M secondary offering") > 0.0
    assert quick_catalyst_score("Foo Corp to acquire Bar Inc in $2B merger") > 0.0


def test_catalyst_score_zero_for_neutral_headline() -> None:
    assert quick_catalyst_score("Company opens new regional office") == 0.0
    assert quick_catalyst_score("") == 0.0


def test_catalyst_score_is_bounded_and_deterministic() -> None:
    h = "Earnings beat; guidance raised; buyback and dividend announced; merger talks"
    s1 = quick_catalyst_score(h)
    s2 = quick_catalyst_score(h)
    assert s1 == s2
    assert 0.0 <= s1 <= 1.0


# ── ShadowJoinLedger.observe ────────────────────────────────────────


def test_observe_first_arrival_per_channel_wins() -> None:
    led = ShadowJoinLedger()
    led.observe("bz1", "ws", 100.0, published_ts=95.0, headline="H", tickers=["AAPL"])
    led.observe("bz1", "ws", 101.0)  # later WS sighting must NOT overwrite
    led.observe("bz1", "rest", 130.0)
    recs = led.pop_ready(now=200.0, linger_s=10.0)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.t_ws == 100.0
    assert rec.t_rest == 130.0
    assert rec.t_published == 95.0
    assert rec.headline == "H"
    assert rec.tickers == ["AAPL"]
    # t_x is reserved and stays None until a future X matcher fills it
    assert rec.t_x is None


def test_observe_rejects_unknown_channel() -> None:
    led = ShadowJoinLedger()
    with pytest.raises(ValueError):
        led.observe("bz1", "telegram", 100.0)


def test_observe_backfills_metadata_from_later_channel() -> None:
    # WS may arrive as a bare id first; REST carries the richer metadata.
    led = ShadowJoinLedger()
    led.observe("bz1", "ws", 100.0)
    led.observe("bz1", "rest", 130.0, published_ts=90.0, headline="Deal",
                tickers=["MSFT"])
    rec = led.pop_ready(now=200.0, linger_s=10.0)[0]
    assert rec.t_published == 90.0
    assert rec.headline == "Deal"
    assert rec.tickers == ["MSFT"]


# ── pop_ready linger semantics ──────────────────────────────────────


def test_pop_ready_respects_linger_window() -> None:
    led = ShadowJoinLedger()
    led.observe("bz1", "ws", 100.0)  # first_seen_ts = 100.0
    # Not yet past the linger window → nothing flushed, still pending.
    assert led.pop_ready(now=105.0, linger_s=10.0) == []
    assert led.pending_count() == 1
    # Past the window → flushed and removed.
    out = led.pop_ready(now=111.0, linger_s=10.0)
    assert [r.item_id for r in out] == ["bz1"]
    assert led.pending_count() == 0


def test_pop_ready_only_emits_ready_records() -> None:
    led = ShadowJoinLedger()
    led.observe("old", "ws", 100.0)
    led.observe("new", "ws", 108.0)
    out = led.pop_ready(now=111.0, linger_s=10.0)
    assert [r.item_id for r in out] == ["old"]
    assert led.pending_count() == 1  # "new" still within linger


def test_flushed_record_is_not_resurrected_on_resighting() -> None:
    # The REST poller re-returns the same "latest" page every cycle; an id that
    # already flushed must NOT be re-added and emitted a second time.
    led = ShadowJoinLedger()
    led.observe("bz1", "ws", 100.0)
    assert [r.item_id for r in led.pop_ready(now=111.0, linger_s=10.0)] == ["bz1"]
    led.observe("bz1", "rest", 200.0)  # re-sighting long after flush
    assert led.pop_ready(now=300.0, linger_s=10.0) == []
    assert led.pending_count() == 0


# ── compute_deltas ──────────────────────────────────────────────────


def test_compute_deltas_signs() -> None:
    rec = ShadowRecord(item_id="x", t_published=90.0, t_ws=100.0, t_rest=130.0)
    d = compute_deltas(rec)
    # positive ws_rest_delta => WS arrived earlier than REST (the advantage)
    assert d["ws_rest_delta_s"] == 30.0
    assert d["pub_ws_delta_s"] == 10.0
    assert d["pub_rest_delta_s"] == 40.0


def test_compute_deltas_none_safe() -> None:
    rec = ShadowRecord(item_id="x", t_ws=100.0)  # no rest, no published
    d = compute_deltas(rec)
    assert d["ws_rest_delta_s"] is None
    assert d["pub_ws_delta_s"] is None


# ── record_to_dict ──────────────────────────────────────────────────


def test_record_to_dict_includes_reserved_tx_and_deltas() -> None:
    rec = ShadowRecord(
        item_id="bz1", headline="ACME FDA approval", tickers=["ACME"],
        source_name="Benzinga", t_published=90.0, t_ws=100.0, t_rest=130.0,
        catalyst_score=0.5,
    )
    d = record_to_dict(rec)
    assert d["item_id"] == "bz1"
    assert d["t_x"] is None            # reserved column present from day one
    assert d["ws_rest_delta_s"] == 30.0
    assert d["catalyst_score"] == 0.5
    assert d["tickers"] == ["ACME"]
    # both epoch and ISO forms so the JSONL is human-inspectable
    assert "t_ws" in d and "t_ws_iso" in d
