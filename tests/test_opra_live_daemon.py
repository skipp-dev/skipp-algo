from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import pytest
from databento.common.error import BentoClientError

from newsstack_fmp.opra_uoa import OpraDefinitionRecord
from services.opra_live_daemon import feed
from services.opra_live_daemon.config import Config
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


class _TradeObj:
    """Attribute surface of a live ``TradeMsg``: NO instrument_class, NO BBO.

    Every routing test above feeds dicts, and dicts pass ``_mapping`` through
    unchanged — which is exactly how the 2026-08-04 outage stayed invisible:
    ``_mapping``'s fixed-key fallback fabricated ``instrument_class`` (=None)
    for every real DBN object, ``_is_definition``'s membership test then
    routed the ENTIRE live stream into the definition sink, and the daemon
    processed 129,617 records into zero counters (measured in-container).
    """

    def __init__(self, *, instrument_id: int = 1, ts: int = 1_000_000_000, sequence: int = 7) -> None:
        self.instrument_id = instrument_id
        self.ts_event = ts
        self.ts_recv = ts + 1_000
        self.sequence = sequence
        self.price = 3.0
        self.size = 100
        self.side = "N"
        self.publisher_id = 20


class _QuoteObj:
    """Attribute surface of a live ``CMBP1Msg``: BBO present, no sequence."""

    def __init__(self, *, instrument_id: int = 1, ts: int = 999_999_000) -> None:
        self.instrument_id = instrument_id
        self.ts_event = ts
        self.ts_recv = ts + 1_000
        self.price = 3.0
        self.size = 100
        self.side = "N"
        self.publisher_id = 20
        self.bid_px_00 = 2.9
        self.ask_px_00 = 3.0


class _DefObj:
    """Attribute surface of a live ``InstrumentDefMsg`` (the fields state uses)."""

    def __init__(self, *, instrument_id: int = 1) -> None:
        self.instrument_id = instrument_id
        self.ts_recv = 500_000_000
        self.underlying = "AAPL"
        self.asset = "AAPL"
        self.strike_price = 200.0
        self.expiration = "2026-07-24"
        self.instrument_class = "C"
        self.raw_symbol = "AAPL  260724C00200000"


class _SymbolMappingObj:
    """A ``SymbolMappingMsg``: instrument_id + ts, no market-data fields.

    123,294 of these arrived in a 20s live sample — they must route to a
    control sink, not into add_trade as phantom unknown-instrument trades.
    """

    def __init__(self) -> None:
        self.instrument_id = 55
        self.ts_event = 1_000_000_000
        self.ts_recv = 1_000_001_000
        self.stype_out_symbol = "AAPL  260724C00200000"


class _SystemObj:
    """A ``SystemMsg`` heartbeat: carries none of the market-data fields."""

    def __init__(self) -> None:
        self.msg = "Heartbeat"


def test_live_trade_objects_route_as_trades_not_definitions() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    assert route_record_import()(state, _QuoteObj()) == "quote"
    assert route_record_import()(state, _TradeObj()) == "trade"
    metrics = state.build_snapshot()["metrics"]
    assert metrics["records_in_window"] == 1


def test_live_definition_object_still_routes_as_definition() -> None:
    state = _state()
    assert route_record_import()(state, _DefObj()) == "definition"
    assert state.build_snapshot()["metrics"]["definition_count"] == 1


def test_control_messages_route_to_a_sink_and_touch_no_counter() -> None:
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    assert route_record_import()(state, _SymbolMappingObj()) == "control"
    assert route_record_import()(state, _SystemObj()) == "control"
    metrics = state.build_snapshot()["metrics"]
    assert metrics["records_in_window"] == 0
    assert metrics["unknown_instruments"] == 0
    assert metrics["pending_instruments"] == 0


def route_record_import():
    from services.opra_live_daemon.feed import route_record as rr

    return rr


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

    source = inspect.getsource(feed)
    assert 'schema="trades"' in source
    assert "subscriptions=3" in source


# ---- feed.run consumes via callbacks, never the iterator (2026-08-04) ------
#
# The iterator path stalled twice in production, measured on the live
# acceptance for #4370: databento-python 0.79.0 pauses the transport when its
# DBNQueue fills during the subscribe-time burst (~40k OPRA definition-snapshot
# records) and the resume path silently no-ops, leaving the feed thread
# starving in DBNQueue.get on an EMPTY queue while the asyncio thread idles
# with reading paused. py-spy-verified; exactly one "record queue is full"
# warning per boot; records_in_window frozen at 0 for 90+ minutes, twice.
# The callback API (add_callback + start) is dispatched by the session
# directly and never touches the DBNQueue, so that mechanic cannot strand it.
#
# _FakeLive therefore makes ITERATION ITSELF the failure: __iter__ raises, so
# any regression back to `for record in client` dies loudly in every test
# below instead of hanging a production shadow for another trading day.


class _FakeLive:
    """Callback-API double for ``db.Live``; iteration is the production bug."""

    instances: ClassVar[list[_FakeLive]] = []
    scripts: ClassVar[list[list[Any]]] = []
    stay_connected: ClassVar[bool] = False
    after_start: ClassVar[list[Any]] = []
    on_iter: ClassVar[Any] = None

    @classmethod
    def reset(
        cls,
        *,
        scripts: list[list[Any]],
        stay_connected: bool = False,
        after_start: list[Any] | None = None,
        on_iter: Any = None,
    ) -> None:
        cls.instances = []
        cls.scripts = list(scripts)
        cls.stay_connected = stay_connected
        cls.after_start = list(after_start or [])
        cls.on_iter = on_iter

    def __init__(self, key: str) -> None:
        self.key = key
        self.subscriptions: list[dict[str, Any]] = []
        self.record_callback: Any = None
        self.started = False
        self.stopped = False
        self._connected = False
        self.script = type(self).scripts.pop(0) if type(self).scripts else []
        type(self).instances.append(self)

    def subscribe(self, **kwargs: Any) -> None:
        self.subscriptions.append(kwargs)

    def add_callback(self, record_callback: Any, exception_callback: Any = None) -> None:
        self.record_callback = record_callback

    def start(self) -> None:
        self.started = True
        self._connected = True
        for record in self.script:
            # Delivered synchronously, the way the session's loop thread would.
            self.record_callback(record)
        self._connected = type(self).stay_connected
        if type(self).after_start:
            type(self).after_start.pop(0)()

    def is_connected(self) -> bool:
        return self._connected and not self.stopped

    def stop(self) -> None:
        self.stopped = True
        self._connected = False

    def __iter__(self) -> Any:
        # Un-hang the run loop first (the old implementation would otherwise
        # reconnect forever and the RED test would hang instead of failing).
        if type(self).on_iter is not None:
            type(self).on_iter()
        raise AssertionError(
            "feed.run iterated the Live client; the 2026-08-04 stall class "
            "(DBNQueue pause without resume) is reachable again"
        )


class _FakeDb:
    Live = _FakeLive


def _config(tmp_path: Path, *, hotlist_path: Path | None = None) -> Config:
    return Config(
        mode="shadow",
        api_key="k",
        dataset="OPRA.PILLAR",
        schema="tcbbo",
        hotlist=("AAPL",),
        hotlist_path=hotlist_path,
        snapshot_path=tmp_path / "snap.json",
        ledger_path=tmp_path / "ledger.jsonl",
        window_seconds=900,
        snapshot_interval_seconds=5.0,
        min_premium=25_000,
    )


def _patch_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    import databento_client

    monkeypatch.setattr(databento_client, "_import_databento", lambda: _FakeDb)
    monkeypatch.setattr(feed, "bootstrap_definitions", lambda *a, **k: [])
    monkeypatch.setattr(feed, "_WAIT_TICK_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(feed.random, "uniform", lambda a, b: 0.0)


def _run_watched(config: Config, state: OpraShadowState, stop: threading.Event) -> None:
    """feed.run with a watchdog: a hang becomes a fast failure, not a stuck CI.

    Measured need, not hypothesis: the first mutation probe against these tests
    (drop ``client.start()``) hung the reconnect loop forever — no record ever
    fires the hooks that set ``stop``, so a regression of that shape would
    freeze the suite instead of turning it red.
    """
    hung = threading.Event()

    def _force_shutdown() -> None:
        hung.set()
        stop.set()

    watchdog = threading.Timer(10.0, _force_shutdown)
    watchdog.start()
    try:
        feed.run(config, state, stop)
    finally:
        watchdog.cancel()
    assert not hung.is_set(), "feed.run hung; the watchdog had to force shutdown"


def test_run_wires_callbacks_and_counts_without_the_iterator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = threading.Event()
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    _FakeLive.reset(
        scripts=[[_quote_row(), _trades_row()]],
        after_start=[stop.set],
        on_iter=stop.set,
    )
    _patch_feed(monkeypatch)

    _run_watched(_config(tmp_path), state, stop)

    (client,) = _FakeLive.instances
    assert client.started
    assert [s["schema"] for s in client.subscriptions] == ["definition", "tcbbo", "trades"]
    metrics = state.build_snapshot()["metrics"]
    assert metrics["records_in_window"] == 1  # the trade counted, the quote stored


def test_run_reconnects_after_a_disconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = threading.Event()
    state = _state()
    _FakeLive.reset(
        scripts=[[], []],
        after_start=[lambda: None, stop.set],
        on_iter=stop.set,
    )
    _patch_feed(monkeypatch)

    _run_watched(_config(tmp_path), state, stop)

    assert len(_FakeLive.instances) == 2
    assert all(client.started for client in _FakeLive.instances)


def test_run_resubscribes_when_the_hotlist_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hotlist_file = tmp_path / "hotlist.txt"
    hotlist_file.write_text("AAPL\n", encoding="utf-8")
    stop = threading.Event()
    state = _state()
    _FakeLive.reset(
        scripts=[[], []],
        stay_connected=True,
        after_start=[
            lambda: hotlist_file.write_text("AAPL\nMSFT\n", encoding="utf-8"),
            stop.set,
        ],
        on_iter=stop.set,
    )
    _patch_feed(monkeypatch)

    _run_watched(_config(tmp_path, hotlist_path=hotlist_file), state, stop)

    first, second = _FakeLive.instances
    assert first.stopped  # graceful teardown before resubscribing
    assert second.subscriptions[0]["symbols"] == ["AAPL.OPT", "MSFT.OPT"]


def test_run_survives_a_poison_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First draft used {"instrument_id": "boom"} as the poison — measured
    # inert: add_trade catches the bad id itself (`except (TypeError,
    # ValueError): return False`), so route_record never raised and the
    # containment path went unexecuted while the test stayed green. The
    # mutation probe (gut the callback's except -> `raise`) survived, which is
    # how the vacuity was caught. The poison therefore raises from
    # route_record itself: the contract under test is "_on_record contains
    # dispatch failures", not "state is un-crashable".
    stop = threading.Event()
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    real_route = feed.route_record

    def _route(state_: OpraShadowState, record: Any) -> str:
        if isinstance(record, dict) and record.get("__poison__"):
            raise RuntimeError("poison record")
        return real_route(state_, record)

    monkeypatch.setattr(feed, "route_record", _route)
    _FakeLive.reset(
        scripts=[[{"__poison__": True}, _trades_row()]],
        after_start=[stop.set],
        on_iter=stop.set,
    )
    _patch_feed(monkeypatch)
    calls: list[dict[str, Any]] = []
    real_usage = feed.databento_usage.record
    monkeypatch.setattr(
        feed.databento_usage,
        "record",
        lambda **kw: (calls.append(kw), real_usage(**kw))[0],
    )

    _run_watched(_config(tmp_path), state, stop)

    assert len(_FakeLive.instances) == 1  # contained: no reconnect churn
    assert state.build_snapshot()["metrics"]["records_in_window"] == 1
    assert any(c.get("errors") == 1 for c in calls)  # the skip is ledgered


def test_run_flushes_usage_batches_and_the_remainder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = threading.Event()
    state = _state()
    state.add_definition(_definition(), ts_ns=500_000_000)
    rows = [_trades_row(sequence=i) for i in range(1, 1502)]  # 1501 distinct fills
    _FakeLive.reset(scripts=[rows], after_start=[stop.set], on_iter=stop.set)
    _patch_feed(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(feed.databento_usage, "record", lambda **kw: calls.append(kw))

    _run_watched(_config(tmp_path), state, stop)

    batches = [c["records"] for c in calls if c.get("records")]
    assert batches == [1000, 501]
