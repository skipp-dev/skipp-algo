from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from databento.common.error import BentoClientError

from newsstack_fmp.opra_uoa import OpraDefinitionRecord
from services.opra_live_daemon.definitions import (
    bootstrap_definitions,
    previous_complete_utc_day,
)
from services.opra_live_daemon.state import OpraShadowState


def _definition(instrument_id: int = 1) -> OpraDefinitionRecord:
    return OpraDefinitionRecord(
        instrument_id=instrument_id,
        underlying="AAPL",
        strike=200.0,
        expiration="2026-07-24",
        option_type="CALL",
        raw_symbol="AAPL  260724C00200000",
    )


def _trade(*, instrument_id: int = 1, ts: int = 1_000_000_000, sequence: int = 1):
    return {
        "instrument_id": instrument_id,
        "ts_event": ts,
        "ts_recv": ts + 1_000,
        "sequence": sequence,
        "price": 3.0,
        "size": 100,
        "side": "N",
        "bid_px_00": 2.9,
        "ask_px_00": 3.0,
        "publisher_id": sequence,
    }


def _state() -> OpraShadowState:
    return OpraShadowState(hotlist=("AAPL",), window_seconds=900, min_premium=25_000)


def test_definition_before_trade_emits_shadow_candidate_with_buy_aggressor() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    assert state.add_trade(_trade())
    snapshot = state.build_snapshot(now=datetime.fromtimestamp(2, tz=UTC))
    candidate = snapshot["candidates"][0]
    assert candidate["aggressor_ind"] == "B"
    assert candidate["sentiment"] == "BULLISH"
    assert candidate["aggressor_source"] == "quote_rule"
    assert candidate["shadow_only"] is True
    assert "_opra_raw" not in candidate


def test_unknown_trade_is_held_until_definition_arrives() -> None:
    state = _state()
    assert not state.add_trade(_trade())
    assert state.build_snapshot()["metrics"]["pending_instruments"] == 1
    assert state.add_definition(_definition()) == 1
    assert state.build_snapshot()["metrics"]["records_in_window"] == 1


def test_duplicate_and_out_of_order_records_are_counted() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    assert state.add_trade(_trade(ts=2_000_000_000, sequence=2))
    assert not state.add_trade(_trade(ts=2_000_000_000, sequence=2))
    assert state.add_trade(_trade(ts=1_000_000_000, sequence=1))
    metrics = state.build_snapshot()["metrics"]
    assert metrics["duplicates"] == 1
    assert metrics["out_of_order"] == 1


def test_out_of_order_trade_older_than_window_is_evicted() -> None:
    # Regression: an out-of-order trade older than the rolling window must be
    # dropped, not left lingering behind a newer trade. `_trades` is an
    # append-order deque, so a late (older) print lands at the right and the
    # left-prefix eviction — which stops at index 0 — used to retain it,
    # emitting a stale trade as a "current" UOA candidate.
    state = OpraShadowState(hotlist=("AAPL",), window_seconds=1, min_premium=25_000)
    state.add_definition(_definition(), ts_ns=1_000_000_000)
    assert state.add_trade(_trade(ts=10_000_000_000, sequence=1))  # t = 10s
    assert state.add_trade(_trade(ts=2_000_000_000, sequence=2))   # out-of-order, 8s stale
    metrics = state.build_snapshot()["metrics"]
    assert metrics["out_of_order"] == 1
    # The 8s-stale print is outside the 1s window and must be evicted, not retained.
    assert metrics["records_in_window"] == 1


def test_non_hotlist_definition_and_trade_never_emit() -> None:
    state = _state()
    other = _definition(instrument_id=2)
    other = OpraDefinitionRecord(**{**other.__dict__, "underlying": "MSFT"})
    state.add_definition(other)
    assert not state.add_trade(_trade(instrument_id=2))
    assert state.build_snapshot()["candidates"] == []


def test_previous_complete_day_is_utc_aligned() -> None:
    start, end = previous_complete_utc_day(
        datetime(2026, 7, 18, 23, 45, tzinfo=UTC)
    )
    assert start.isoformat() == "2026-07-17T00:00:00+00:00"
    assert end.isoformat() == "2026-07-18T00:00:00+00:00"


def test_previous_complete_day_skips_weekend() -> None:
    sunday_start, sunday_end = previous_complete_utc_day(
        datetime(2026, 7, 19, 8, tzinfo=UTC)
    )
    monday_start, monday_end = previous_complete_utc_day(
        datetime(2026, 7, 20, 8, tzinfo=UTC)
    )
    assert sunday_start.isoformat() == "2026-07-17T00:00:00+00:00"
    assert sunday_end.isoformat() == "2026-07-18T00:00:00+00:00"
    assert monday_start == sunday_start
    assert monday_end == sunday_end


def test_definition_bootstrap_uses_parent_symbology() -> None:
    class Provider:
        request: dict[str, object] | None = None

        def get_range(self, **kwargs):
            self.request = kwargs
            return type(
                "Store",
                (),
                {
                    "to_df": lambda _self: pd.DataFrame(
                        [
                            {
                                "instrument_id": 1,
                                "underlying": "AAPL",
                                "strike_price": 200.0,
                                "expiration": "2026-07-24",
                                "instrument_class": "C",
                                "raw_symbol": "AAPL  260724C00200000",
                            }
                        ]
                    )
                },
            )()

    provider = Provider()
    records = bootstrap_definitions(
        provider,
        symbols=["AAPL.OPT"],
        instant=datetime(2026, 7, 18, 23, 45, tzinfo=UTC),
    )
    assert provider.request is not None
    assert provider.request["stype_in"] == "parent"
    assert records == [_definition()]


def test_definition_bootstrap_falls_back_over_unavailable_weekday() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument_id": 1,
                "underlying": "AAPL",
                "strike_price": 200.0,
                "expiration": "2026-07-24",
                "instrument_class": "C",
                "raw_symbol": "AAPL  260724C00200000",
            }
        ]
    )

    class Provider:
        starts: list[str]

        def __init__(self) -> None:
            self.starts = []

        def get_range(self, **kwargs):
            self.starts.append(str(kwargs["start"]))
            if len(self.starts) == 1:
                raise BentoClientError(
                    422,
                    message="data_start_after_available_end",
                )
            return type("Store", (), {"to_df": lambda _self: frame})()

    provider = Provider()
    records = bootstrap_definitions(
        provider,
        symbols=["AAPL.OPT"],
        instant=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )
    assert provider.starts == [
        "2026-07-20T00:00:00+00:00",
        "2026-07-17T00:00:00+00:00",
    ]
    assert records == [_definition()]


def test_hotlist_remove_purges_removed_underlying() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    state.add_trade(_trade())
    state.update_hotlist(("MSFT",))
    snapshot = state.build_snapshot()
    assert snapshot["hotlist"] == ["MSFT"]
    assert snapshot["metrics"]["records_in_window"] == 0


def test_new_session_clears_previous_session_state() -> None:
    state = _state()
    day_one = int(datetime(2026, 7, 17, 14, tzinfo=UTC).timestamp() * 1e9)
    day_two = int(datetime(2026, 7, 18, 14, tzinfo=UTC).timestamp() * 1e9)
    state.add_definition(_definition(), ts_ns=day_one)
    state.add_trade(_trade(ts=day_one))
    state.add_definition(_definition(), ts_ns=day_two)
    assert state.build_snapshot()["metrics"]["records_in_window"] == 0
    assert state.session_date == "2026-07-18"


# ---- trades as count source, tcbbo as quote source (issue #4368) -----------
#
# Measured 2026-08-04 on the recorded live feed (10s SPY.OPT, both schemas):
# tcbbo records carry NO sequence field at all, and 30/685 prints (4.4%) were
# genuine separate child fills identical in (instrument, ts_event, price,
# size, publisher) — distinguishable ONLY by the trades-schema sequence
# (685/685 populated, all colliding groups fully distinct). The daemon
# therefore counts from the trades schema and keeps tcbbo purely as the
# BBO-at-trade source for aggressor classification.


def _trades_row(*, instrument_id: int = 1, ts: int = 1_000_000_000, sequence: int = 1,
                price: float = 3.0, size: int = 100):
    """Shape of a TradeMsg row: sequence populated, NO bid/ask fields."""
    return {
        "instrument_id": instrument_id, "ts_event": ts, "ts_recv": ts + 1_000,
        "sequence": sequence, "price": price, "size": size, "side": "N",
        "publisher_id": 20,
    }


def _quote_row(*, instrument_id: int = 1, ts: int = 999_999_000,
               bid: float = 2.9, ask: float = 3.0):
    """Shape of a CMBP1Msg (tcbbo) row: bid/ask present, NO sequence field."""
    return {
        "instrument_id": instrument_id, "ts_event": ts, "ts_recv": ts + 1_000,
        "price": 3.0, "size": 100, "side": "N",
        "bid_px_00": bid, "ask_px_00": ask, "publisher_id": 20,
    }


def test_identical_multi_fills_with_distinct_sequences_all_count() -> None:
    # The measured 4.4%: a large order split into identical child fills must
    # not be deduplicated away — that is the burst UOA exists to count.
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    state.update_quote(_quote_row())
    assert state.add_trade(_trades_row(sequence=101))
    assert state.add_trade(_trades_row(sequence=102))
    metrics = state.build_snapshot()["metrics"]
    assert metrics["records_in_window"] == 2
    assert metrics["duplicates"] == 0


def test_replayed_trade_with_same_sequence_is_still_deduplicated() -> None:
    # Reconnect replay resends the SAME record (same sequence) — dedup must
    # keep working for exactly that case.
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    state.update_quote(_quote_row())
    assert state.add_trade(_trades_row(sequence=101))
    assert not state.add_trade(_trades_row(sequence=101))
    assert state.build_snapshot()["metrics"]["duplicates"] == 1


def test_aggressor_side_comes_from_the_quote_store() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    state.update_quote(_quote_row(bid=2.9, ask=3.0))
    assert state.add_trade(_trades_row(price=3.0))  # trades at the stored ask
    candidate = state.build_snapshot(now=datetime.fromtimestamp(2, tz=UTC))["candidates"][0]
    assert candidate["aggressor_ind"] == "B"
    assert candidate["aggressor_source"] == "quote_rule"
    assert candidate["nbbo_bid"] == 2.9
    assert candidate["nbbo_ask"] == 3.0


def test_trade_before_any_quote_counts_with_unknown_side() -> None:
    # A trades record arriving before its instrument's first tcbbo record
    # must COUNT (never drop data) and classify as unknown, fail-open on side.
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    assert state.add_trade(_trades_row())
    snapshot = state.build_snapshot(now=datetime.fromtimestamp(2, tz=UTC))
    assert snapshot["metrics"]["records_in_window"] == 1
    candidate = snapshot["candidates"][0]
    assert candidate["aggressor_source"] == "unknown"


def test_quote_record_is_never_counted_as_a_trade() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    state.update_quote(_quote_row())
    assert state.build_snapshot()["metrics"]["records_in_window"] == 0


def test_feed_routes_quotes_and_trades_to_their_paths() -> None:
    from services.opra_live_daemon.feed import route_record

    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    assert route_record(state, _quote_row()) == "quote"
    assert route_record(state, _trades_row()) == "trade"
    metrics = state.build_snapshot()["metrics"]
    assert metrics["records_in_window"] == 1  # the quote was stored, not counted


def test_feed_subscribes_the_trades_schema_alongside_tcbbo() -> None:
    # Source pin: dropping either subscription silently reverts to the
    # 4.4%-undercount regime measured in #4368.
    import inspect

    from services.opra_live_daemon import feed

    source = inspect.getsource(feed)
    assert 'schema="trades"' in source
    assert "subscriptions=3" in source
