"""Unit tests for the Databento live-bar cache feed (Task 1.2).

Drives ``DatabentoQuoteFeed`` with recorded/synthetic ``ohlcv-1s`` record
streams the same way ``test_a0_fast_live_runtime.py`` /
``test_feed_reconnect_and_metrics.py`` drive their consumers: a fake client
object (or factory) that yields plain fake records instead of opening a real
``db.Live`` network connection. No Databento API key required.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import databento as db
import pytest
from databento_dbn import OHLCVMsg, RType, SystemCode

from open_prep.databento_quote_feed import (
    _BARRIER_SENTINEL,
    BarState,
    DatabentoQuoteFeed,
    resolve_current_symbol_support,
)

_ET = ZoneInfo("America/New_York")
_REPLAY_START = datetime(2026, 7, 21, 13, 30, tzinfo=UTC)

# Nanosecond epoch for 2026-07-21 10:00:00 ET (well inside the regular
# trading session, away from the 09:30 open boundary) plus small per-second
# increments. NOTE: an earlier value here (2026-07-15 07:30:05 ET) was
# actually pre-market and only ever ended up in the cache because the RTH
# gate didn't exist yet — fixed alongside adding that gate.
_BASE_TS_EVENT_NS = 1_784_642_400_000_000_000

_END_OF_INTERVAL = 4
_REPLAY_COMPLETED = 3


def _ns_et(hour: int, minute: int, second: int = 0) -> int:
    """Epoch nanoseconds for 2026-07-21 (a normal NYSE trading Tuesday) at
    the given ET local time."""
    return int(datetime(2026, 7, 21, hour, minute, second, tzinfo=_ET).timestamp() * 1e9)


# Fake record classes named exactly like the real databento_dbn wire types
# (mirrors test_a0_fast_live_runtime.py / test_feed_reconnect_and_metrics.py):
# the feed dispatches on ``type(record).__name__``, so the class name is part
# of the fixture contract, not just its attributes.


class SymbolMappingMsg:
    def __init__(self, instrument_id: int, symbol: str) -> None:
        self.instrument_id = instrument_id
        self.stype_out_symbol = symbol


class SystemMsg:
    def __init__(self, code: Any) -> None:
        self.code = code


class OhlcvMsg:
    def __init__(
        self,
        *,
        instrument_id: int,
        open_: int,
        high: int,
        low: int,
        close: int,
        volume: int,
        ts_event: int,
        ts_recv: int,
    ) -> None:
        self.instrument_id = instrument_id
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.ts_event = ts_event
        self.ts_recv = ts_recv


def _ohlcv(
    *,
    instrument_id: int = 1,
    seconds_offset: int = 0,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
    volume: int = 100,
    ts_recv_offset_ns: int = 50_000_000,
) -> OhlcvMsg:
    ts_event = _BASE_TS_EVENT_NS + seconds_offset * 1_000_000_000
    return OhlcvMsg(
        instrument_id=instrument_id,
        open_=int(open_ * 1e9),
        high=int(high * 1e9),
        low=int(low * 1e9),
        close=int(close * 1e9),
        volume=volume,
        ts_event=ts_event,
        ts_recv=ts_event + ts_recv_offset_ns,
    )


def _symbol_mapping(instrument_id: int, symbol: str) -> SymbolMappingMsg:
    return SymbolMappingMsg(instrument_id, symbol)


def _system_msg(code: int) -> SystemMsg:
    return SystemMsg(code)


class _FakeClient:
    """Minimal stand-in for db.Live: records or raises Exceptions on iteration."""

    def __init__(self, records: list[Any]) -> None:
        self.records = records
        self.subscription: dict[str, Any] = {}
        self.stopped = False

    def subscribe(self, **kwargs: Any) -> None:
        self.subscription = kwargs

    def __iter__(self):
        for item in self.records:
            if isinstance(item, Exception):
                raise item
            yield item

    def stop(self) -> None:
        self.stopped = True


def _make_feed(records: list[Any], **kwargs: Any) -> tuple[DatabentoQuoteFeed, _FakeClient]:
    client = _FakeClient(records)
    feed = DatabentoQuoteFeed(
        ["NVDA"],
        client,
        replay_start=_REPLAY_START,
        **kwargs,
    )
    return feed, client


def _start_and_join(feed: DatabentoQuoteFeed, *, timeout: float = 3.0) -> None:
    """Start the feed, wait for one full pass through the (finite) fixture
    stream to complete, then stop.

    Mirrors ``test_feed_reconnect_and_metrics.py``'s ``_run_feed_loop_until``:
    the feed loop retries forever by design (ported verbatim from feed.py),
    so tests poll an observable condition and then explicitly call stop()
    rather than waiting for the thread to die on its own.
    ``reconnect_attempts`` increments right before every backoff sleep —
    including after a clean, error-free pass through a finite stream — so it
    reliably signals "the whole fixture has already been pushed onto the
    ingest queue" without depending on wall-clock guesses. stop() itself
    performs a bounded, blocking drain of the ingest queue, so any bar still
    in flight at that point is still captured before stop() returns.
    """
    feed.start()
    deadline = time.monotonic() + timeout
    while (
        feed.telemetry.snapshot()["reconnect_attempts"] < 1
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    feed.stop()


class TestBasicIngestion:
    def test_feed_ingests_ohlcv_and_serves_latest(self) -> None:
        # Real Databento fires END_OF_INTERVAL once per second (after every
        # symbol's bar for that second), not once for the whole stream — so
        # the fixture barriers each bar individually.
        records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(seconds_offset=0, close=100.5, high=101.0, low=99.0, volume=100),
            _system_msg(_END_OF_INTERVAL),
            _ohlcv(seconds_offset=1, close=101.0, high=101.5, low=100.0, volume=50),
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        bar = feed.latest_bar("NVDA")
        assert bar is not None
        assert bar.close == pytest.approx(101.0)
        assert feed.cumulative_volume("NVDA") == 150
        high, low = feed.session_high_low("NVDA")
        assert high == pytest.approx(101.5)
        assert low == pytest.approx(99.0)

    def test_unknown_symbol_returns_empty_defaults(self) -> None:
        feed, _client = _make_feed([_symbol_mapping(1, "NVDA")])
        _start_and_join(feed)

        assert feed.latest_bar("AAPL") is None
        assert feed.cumulative_volume("AAPL") == 0
        assert feed.session_high_low("AAPL") == (None, None)

    @pytest.mark.parametrize(
        ("canonical", "provider"),
        [("BF-B", "BF.B"), ("BRK-A", "BRK.A"), ("BRK-B", "BRK.B")],
    )
    def test_share_class_symbols_use_provider_alias_but_cache_canonical_symbol(
        self,
        canonical: str,
        provider: str,
    ) -> None:
        records = [
            _symbol_mapping(1, provider),
            _ohlcv(close=100.5, volume=100),
            _system_msg(_END_OF_INTERVAL),
        ]
        client = _FakeClient(records)
        feed = DatabentoQuoteFeed(
            [canonical],
            client,
            replay_start=_REPLAY_START,
            reconnect_delay_secs=30.0,
        )

        _start_and_join(feed)

        assert client.subscription["symbols"] == [provider]
        assert feed.latest_bar(canonical) is not None
        assert feed.latest_bar(canonical).symbol == canonical
        assert feed.cumulative_volume(canonical) == 100

    def test_known_unsupported_symbols_are_filtered_before_subscription(self) -> None:
        client = _FakeClient([])
        feed = DatabentoQuoteFeed(
            ["AAPL", "CTA-PA"],
            client,
            replay_start=_REPLAY_START,
            reconnect_delay_secs=30.0,
        )

        _start_and_join(feed)

        assert client.subscription["symbols"] == ["AAPL"]
        snap = feed.telemetry.snapshot()
        assert snap["symbols_requested"] == 2
        assert snap["symbols_subscribed"] == 1
        assert snap["symbols_filtered"] == {"unsupported_symbol": 1}
        assert (
            'databento_quote_feed_symbols_filtered{reason="unsupported_symbol"} 1'
            in feed.telemetry.render_prometheus()
        )


class TestSymbolSupportPreflight:
    def test_resolve_current_symbol_support_classifies_failed_and_partial(self) -> None:
        class _Symbology:
            def __init__(self) -> None:
                self.kwargs: dict[str, Any] = {}

            def resolve(self, **kwargs: Any) -> dict[str, Any]:
                self.kwargs = kwargs
                return {
                    "result": {
                        "AAPL": [{"s": "AAPL", "d0": "2026-07-21", "d1": "2026-07-22"}],
                        "BRK.B": [],
                        "HALF": [{"s": "HALF", "d0": "2026-07-21", "d1": "2026-07-21"}],
                    },
                    "not_found": ["BRK.B"],
                    "partial": ["HALF"],
                }

        symbology = _Symbology()
        client = type("_Historical", (), {"symbology": symbology})()

        unresolved = resolve_current_symbol_support(
            "unused",
            [" aapl ", "BRK.B", "HALF", "AAPL", ""],
            session_date=date(2026, 7, 21),
            client=client,
        )

        assert unresolved == {
            "BRK.B": "symbol_resolution_failed",
            "HALF": "symbol_resolution_partial",
        }
        assert symbology.kwargs == {
            "dataset": "EQUS.MINI",
            "symbols": ["AAPL", "BRK.B", "HALF"],
            "stype_in": "raw_symbol",
            "stype_out": "instrument_id",
            "start_date": "2026-07-21",
            "end_date": "2026-07-22",
        }

    def test_live_resolution_exclusions_never_reach_subscription(self) -> None:
        client = _FakeClient([])
        feed = DatabentoQuoteFeed(
            ["AAPL", "BRK-B", "NOPE"],
            client,
            replay_start=_REPLAY_START,
            reconnect_delay_secs=30.0,
            symbol_support_resolver=lambda symbols: {
                symbol: "symbol_resolution_failed"
                for symbol in symbols
                if symbol == "NOPE"
            },
        )

        _start_and_join(feed)

        assert client.subscription["symbols"] == ["AAPL", "BRK.B"]
        assert feed.telemetry.snapshot()["symbols_filtered"] == {
            "symbol_resolution_failed": 1,
        }

    def test_preflight_outage_fails_open_with_visible_metric(self) -> None:
        def _raise(_symbols: list[str]) -> dict[str, str]:
            raise RuntimeError("synthetic resolver outage")

        client = _FakeClient([])
        feed = DatabentoQuoteFeed(
            ["AAPL"],
            client,
            replay_start=_REPLAY_START,
            reconnect_delay_secs=30.0,
            symbol_support_resolver=_raise,
        )

        _start_and_join(feed)

        assert client.subscription["symbols"] == ["AAPL"]
        assert feed.telemetry.snapshot()["symbol_preflight_success"] is False
        assert "databento_quote_feed_symbol_preflight_success 0" in (
            feed.telemetry.render_prometheus()
        )

    def test_all_symbols_rejected_by_preflight_aborts_source_build(self) -> None:
        with pytest.raises(ValueError, match="no Databento-supported entries"):
            DatabentoQuoteFeed(
                ["NOPE"],
                _FakeClient([]),
                replay_start=_REPLAY_START,
                symbol_support_resolver=lambda symbols: {
                    symbol: "symbol_resolution_failed" for symbol in symbols
                },
            )


class TestEndOfIntervalBarrier:
    def test_pending_bar_not_visible_until_end_of_interval(self) -> None:
        """A bar staged in _pending must not be visible before the barrier
        (or the final shutdown flush) commits it to the shared cache."""
        records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(seconds_offset=0, close=100.5, volume=100),
            # No END_OF_INTERVAL — the feed loop cleanly exhausts this finite
            # stream and enters its (long, default) reconnect backoff, giving
            # this test a wide window to observe the pre-barrier state.
        ]
        feed, _client = _make_feed(records)
        feed.start()

        deadline = time.monotonic() + 2.0
        while (
            feed.telemetry.snapshot()["records_received"] < 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        # Give the ingest thread a moment to actually drain the queued item
        # into _pending (it races the assertion below, not the barrier).
        time.sleep(0.1)

        assert feed.telemetry.snapshot()["records_received"] == 1
        assert feed.latest_bar("NVDA") is None, "bar became visible without a barrier"

        feed.stop()  # triggers the final-flush safety net
        assert feed.latest_bar("NVDA") is not None

    def test_barrier_flush_makes_batch_visible_atomically(self) -> None:
        records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(seconds_offset=0, close=100.5, volume=100),
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        assert feed.latest_bar("NVDA") is not None
        assert feed.cumulative_volume("NVDA") == 100


class TestSessionBoundary:
    def test_new_session_date_resets_cumulative_volume_and_high_low(self) -> None:
        day1_ns = _BASE_TS_EVENT_NS
        day2_ns = int(
            datetime(2026, 7, 22, 13, 30, 5, tzinfo=UTC).timestamp() * 1e9
        )
        records = [
            _symbol_mapping(1, "NVDA"),
            OhlcvMsg(
                instrument_id=1,
                open_=int(100 * 1e9),
                high=int(105 * 1e9),
                low=int(95 * 1e9),
                close=int(100 * 1e9),
                volume=1000,
                ts_event=day1_ns,
                ts_recv=day1_ns,
            ),
            _system_msg(_END_OF_INTERVAL),
            OhlcvMsg(
                instrument_id=1,
                open_=int(200 * 1e9),
                high=int(202 * 1e9),
                low=int(198 * 1e9),
                close=int(200 * 1e9),
                volume=10,
                ts_event=day2_ns,
                ts_recv=day2_ns,
            ),
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        assert feed.cumulative_volume("NVDA") == 10
        high, low = feed.session_high_low("NVDA")
        assert high == pytest.approx(202.0)
        assert low == pytest.approx(198.0)


class TestRegularTradingHoursGate:
    """The whole open_prep/a0 pipeline is RTH-centric (the producer hot path
    this feed backs only runs while market_session == "regular"). Pre-market
    and post-market bars must not reach the cache — mirrors
    a0_stream_state.py's OUTSIDE_SESSION early return (no mutation at all)."""

    def test_premarket_and_postmarket_bars_are_excluded_entirely(self) -> None:
        records = [
            _symbol_mapping(1, "NVDA"),
            OhlcvMsg(
                instrument_id=1,
                open_=int(100 * 1e9),
                high=int(100 * 1e9),
                low=int(100 * 1e9),
                close=int(100 * 1e9),
                volume=999,
                ts_event=_ns_et(8, 0),  # 08:00 ET — pre-market
                ts_recv=_ns_et(8, 0),
            ),
            _system_msg(_END_OF_INTERVAL),
            OhlcvMsg(
                instrument_id=1,
                open_=int(100 * 1e9),
                high=int(100 * 1e9),
                low=int(100 * 1e9),
                close=int(100 * 1e9),
                volume=888,
                ts_event=_ns_et(17, 0),  # 17:00 ET — post-market (close is 16:00)
                ts_recv=_ns_et(17, 0),
            ),
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        # No regular-session bar ever arrived -> no cache entry at all.
        assert feed.latest_bar("NVDA") is None
        assert feed.cumulative_volume("NVDA") == 0
        assert feed.session_high_low("NVDA") == (None, None)

    def test_extreme_premarket_and_postmarket_bars_do_not_contaminate_session_high_low(
        self,
    ) -> None:
        """A thin illiquid after-hours spike must not set a false
        session_high/low, and pre/post-market volume must not inflate
        cumulative_volume — the regression this whole gate exists for."""
        records = [
            _symbol_mapping(1, "NVDA"),
            OhlcvMsg(
                instrument_id=1,
                open_=int(150 * 1e9),
                high=int(150 * 1e9),  # would blow session_high way up if leaked
                low=int(50 * 1e9),  # would blow session_low way down if leaked
                close=int(120 * 1e9),
                volume=1_000_000,
                ts_event=_ns_et(8, 0),  # pre-market
                ts_recv=_ns_et(8, 0),
            ),
            _system_msg(_END_OF_INTERVAL),
            OhlcvMsg(
                instrument_id=1,
                open_=int(100 * 1e9),
                high=int(101 * 1e9),
                low=int(99 * 1e9),
                close=int(100.5 * 1e9),
                volume=100,
                ts_event=_ns_et(10, 0),  # regular session
                ts_recv=_ns_et(10, 0),
            ),
            _system_msg(_END_OF_INTERVAL),
            OhlcvMsg(
                instrument_id=1,
                open_=int(200 * 1e9),
                high=int(200 * 1e9),  # would blow session_high way up if leaked
                low=int(10 * 1e9),  # would blow session_low way down if leaked
                close=int(150 * 1e9),
                volume=2_000_000,
                ts_event=_ns_et(17, 0),  # post-market
                ts_recv=_ns_et(17, 0),
            ),
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        # Only the single regular-session bar's volume/price/high/low counts.
        assert feed.cumulative_volume("NVDA") == 100
        high, low = feed.session_high_low("NVDA")
        assert high == pytest.approx(101.0)
        assert low == pytest.approx(99.0)
        bar = feed.latest_bar("NVDA")
        assert bar is not None
        assert bar.close == pytest.approx(100.5)


class TestStreamEndFlushesPending:
    def test_stream_end_without_trailing_barrier_still_flushes(self) -> None:
        """A recorded stream that ends mid-interval (no closing
        END_OF_INTERVAL) must not silently lose the last bar."""
        records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(seconds_offset=0, close=100.5, volume=100),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        assert feed.latest_bar("NVDA") is not None
        assert feed.cumulative_volume("NVDA") == 100


class TestRejectedRecords:
    def test_unmapped_instrument_and_invalid_bar_are_rejected_not_cached(self) -> None:
        invalid_bar = _ohlcv(instrument_id=1, seconds_offset=0)
        invalid_bar.close = None
        records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(instrument_id=99, seconds_offset=0),  # unmapped instrument
            invalid_bar,
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        assert feed.latest_bar("NVDA") is None
        snap = feed.telemetry.snapshot()
        assert snap["record_rejections"].get("unmapped_symbol") == 1
        assert snap["record_rejections"].get("invalid_record") == 1


class TestDataAgeTelemetry:
    def test_data_age_ms_gauge_reflects_latest_bar_lag(self) -> None:
        records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(seconds_offset=0, close=100.5, volume=100, ts_recv_offset_ns=250_000_000),
            _system_msg(_END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        snap = feed.telemetry.snapshot()
        assert snap["data_age_ms"] == pytest.approx(250.0, abs=1.0)
        rendered = feed.telemetry.render_prometheus()
        assert "databento_quote_feed_data_age_ms " in rendered
        assert "databento_quote_feed_connected" in rendered

    def test_real_databento_ohlcv_and_system_records_are_accepted(self) -> None:
        """Compatibility check with the actual databento_dbn wire types."""
        event_ns = _BASE_TS_EVENT_NS
        ohlcv = OHLCVMsg(
            RType.OHLCV_1S,
            1,
            1,
            event_ns,
            int(100 * 1e9),
            int(101 * 1e9),
            int(99 * 1e9),
            int(100.5 * 1e9),
            100,
        )
        records = [
            _symbol_mapping(1, "NVDA"),
            ohlcv,
            SystemMsg(SystemCode.END_OF_INTERVAL),
        ]
        feed, _client = _make_feed(records)
        _start_and_join(feed)

        bar = feed.latest_bar("NVDA")
        assert bar is not None
        assert bar.ts_event == event_ns / 1_000_000_000


class TestReconnectAndReplay:
    def test_reconnect_after_bento_error_resubscribes_from_last_committed_bar(self) -> None:
        first_records = [
            _symbol_mapping(1, "NVDA"),
            _ohlcv(seconds_offset=0, close=100.5, volume=100),
            _system_msg(_END_OF_INTERVAL),
            db.BentoError("connection reset"),
        ]
        second_records: list[Any] = []
        clients: list[_FakeClient] = []

        def factory() -> _FakeClient:
            records = first_records if not clients else second_records
            client = _FakeClient(records)
            clients.append(client)
            return client

        feed = DatabentoQuoteFeed(
            ["NVDA"],
            factory,
            replay_start=_REPLAY_START,
            reconnect_delay_secs=0.02,
            reconnect_backoff_secs=0.02,
            # This test pins the cursor-advancement arithmetic against the
            # fixed fixture timestamps; the gateway-window clamp (its own
            # tests below) would rewrite them to wall-clock-relative values.
            replay_start_max_age=None,
        )
        feed.start()
        deadline = time.monotonic() + 3.0
        while len(clients) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        feed.stop()

        assert len(clients) >= 2, "feed did not reconnect after BentoError"
        second_start = clients[1].subscription["start"]
        expected_ts = _BASE_TS_EVENT_NS / 1_000_000_000 + 1.0
        assert second_start.timestamp() == pytest.approx(expected_ts, abs=0.01)
        assert feed.telemetry.snapshot()["bento_errors"] >= 1
        assert feed.telemetry.snapshot()["reconnect_attempts"] >= 1

    def test_circuit_breaker_trips_after_max_consecutive_failures(self) -> None:
        """consecutive_failures resets to 0 right after a successful
        subscribe() (ported from feed.py) — so, matching feed.py's own
        ``test_consecutive_failures_trip_circuit_breaker``, the failure must
        happen at subscribe() itself (a persistent connect-time failure, e.g.
        bad entitlement) to accumulate across reconnects. A failure raised
        only during iteration is individually retried without ever tripping
        the breaker — see ``test_reconnect_after_bento_error_...`` above."""
        failure = db.BentoError("persistent failure")

        class _RefusingClient(_FakeClient):
            def subscribe(self, **kwargs: Any) -> None:
                super().subscribe(**kwargs)
                raise failure

        feed = DatabentoQuoteFeed(
            ["NVDA"],
            lambda: _RefusingClient([]),
            replay_start=_REPLAY_START,
            reconnect_delay_secs=0.01,
            reconnect_backoff_secs=0.01,
            max_reconnect_attempts=2,
            max_consecutive_failures=3,
        )
        feed.start()
        deadline = time.monotonic() + 3.0
        while (
            feed.telemetry.snapshot()["circuit_breakers"] < 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        feed.stop()

        snap = feed.telemetry.snapshot()
        assert snap["circuit_breakers"] == 1
        assert snap["bento_errors"] >= 3


class TestThreadSafety:
    def test_concurrent_reads_during_ingestion_do_not_raise(self) -> None:
        """No exceptions across 4 concurrent reader threads, plus a mid-flight
        consistency check: session_high/session_low are two separate
        assignments inside ``_apply_bar_to_cache`` (both under _cache_lock),
        so a reader could in principle observe a torn update between them
        without the lock (high already bumped, low not yet). Asserting
        high >= low on every concurrently-read snapshot is a real invariant
        the lock is responsible for — not just "no crash"."""
        records: list[Any] = [_symbol_mapping(1, "NVDA")]
        for i in range(50):
            records.append(_ohlcv(seconds_offset=i, close=100.0 + i, volume=10))
            records.append(_system_msg(_END_OF_INTERVAL))
        feed, _client = _make_feed(records)

        errors: list[BaseException] = []

        def reader() -> None:
            try:
                for _ in range(200):
                    feed.latest_bar("NVDA")
                    feed.cumulative_volume("NVDA")
                    high, low = feed.session_high_low("NVDA")
                    if high is not None and low is not None:
                        assert high >= low, f"torn session hi/lo read: high={high} low={low}"
            except BaseException as exc:
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(4)]
        for t in readers:
            t.start()
        _start_and_join(feed)
        for t in readers:
            t.join(timeout=2)

        assert not errors
        assert feed.cumulative_volume("NVDA") == 500


class TestReplayBarrierNonDroppable:
    """Blocker (4), verified live 2026-07-27: during intraday replay Databento
    emits an END_OF_INTERVAL barrier per interval, but the queue is kept full by
    the blocking bar puts. A ``put_nowait`` barrier is then silently dropped
    (never counted), letting multiple intervals' bars overwrite in ``_pending``
    and undercounting cumulative volume at the session-open backfill (queue=50
    stress lost up to 2.2%). The fix blocks the barrier during replay so every
    interval flushes exactly once, at any queue size."""

    def test_replay_barrier_blocks_until_space_never_dropped(self) -> None:
        feed, _ = _make_feed([], queue_max=1)
        feed._queue.put_nowait(object())  # saturate the single slot
        done = threading.Event()

        def enqueue() -> None:
            feed._enqueue_barrier(replay_active=True)
            done.set()

        t = threading.Thread(target=enqueue, daemon=True)
        t.start()
        # A full queue must make the replay barrier BLOCK, not drop-and-return.
        assert not done.wait(0.4), "replay barrier returned while queue full (dropped)"
        feed._queue.get_nowait()  # free a slot
        assert done.wait(1.0), "replay barrier never enqueued after space freed"
        t.join(timeout=1.0)
        assert feed._queue.get_nowait() is _BARRIER_SENTINEL

    def test_live_barrier_is_best_effort_dropped_when_full(self) -> None:
        feed, _ = _make_feed([], queue_max=1)
        filler = object()
        feed._queue.put_nowait(filler)
        # A live barrier must NOT block on a full queue (best-effort drop) —
        # this returns immediately and leaves only the filler behind.
        feed._enqueue_barrier(replay_active=False)
        assert feed._queue.qsize() == 1
        assert feed._queue.get_nowait() is filler

    def test_only_live_bar_queue_pressure_counts_as_a_drop(self) -> None:
        feed, _ = _make_feed([], queue_max=1)
        feed._queue.put_nowait(object())
        bar = BarState("AAPL", 100.0, 101.0, 99.0, 100.5, 100, 1.0, 1.0)

        feed._enqueue_bar("AAPL", bar, replay_active=False)
        assert feed.telemetry.snapshot()["queue_dropped"] == 1

        replay_done = threading.Event()

        def enqueue_replay() -> None:
            feed._enqueue_bar("AAPL", bar, replay_active=True)
            replay_done.set()

        thread = threading.Thread(target=enqueue_replay, daemon=True)
        thread.start()
        assert not replay_done.wait(0.4)
        assert feed.telemetry.snapshot()["queue_dropped"] == 1
        feed._queue.get_nowait()
        assert replay_done.wait(1.0)
        thread.join(timeout=1.0)


class TestSupervisorRestart:
    def test_circuit_breaker_rearms_via_supervisor_instead_of_dying(self) -> None:
        """After the circuit breaker trips the feed must NOT die permanently
        (the pre-hardening behavior). The supervisor cools down, re-arms, and
        reconnects, so a transient multi-failure outage self-heals without a
        process restart. A short cooldown makes repeated re-arms observable
        in-test; the persistent connect-time failure (subscribe raises) is what
        accumulates consecutive failures past the breaker (see
        ``test_circuit_breaker_trips_after_max_consecutive_failures``)."""
        failure = db.BentoError("persistent failure")

        class _RefusingClient(_FakeClient):
            def subscribe(self, **kwargs: Any) -> None:
                super().subscribe(**kwargs)
                raise failure

        feed = DatabentoQuoteFeed(
            ["NVDA"],
            lambda: _RefusingClient([]),
            replay_start=_REPLAY_START,
            reconnect_delay_secs=0.01,
            reconnect_backoff_secs=0.01,
            max_reconnect_attempts=2,
            max_consecutive_failures=2,
            supervisor_cooldown_secs=0.02,
        )
        feed.start()
        deadline = time.monotonic() + 3.0
        while (
            feed.telemetry.snapshot()["supervisor_restarts"] < 2
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        # Sampled BEFORE stop(): the feed thread is still alive because the
        # supervisor re-armed it, not because it never tripped.
        alive_after_rearm = feed._feed_thread is not None and feed._feed_thread.is_alive()
        feed.stop()

        snap = feed.telemetry.snapshot()
        assert snap["supervisor_restarts"] >= 2, "supervisor did not re-arm the feed after circuit-break"
        assert snap["circuit_breakers"] >= 2, "breaker should keep tripping+re-arming, not die after one trip"
        assert alive_after_rearm, "feed thread died instead of being supervised"

    def test_supervisor_cooldown_is_interrupted_by_stop(self) -> None:
        """A stop() during the (here long) supervisor cooldown must break out
        promptly rather than block for the full cooldown — so shutdown stays
        responsive even mid-cooldown."""
        failure = db.BentoError("persistent failure")

        class _RefusingClient(_FakeClient):
            def subscribe(self, **kwargs: Any) -> None:
                super().subscribe(**kwargs)
                raise failure

        feed = DatabentoQuoteFeed(
            ["NVDA"],
            lambda: _RefusingClient([]),
            replay_start=_REPLAY_START,
            reconnect_delay_secs=0.01,
            reconnect_backoff_secs=0.01,
            max_reconnect_attempts=2,
            max_consecutive_failures=2,
            supervisor_cooldown_secs=30.0,  # long: only stop() should end it
        )
        feed.start()
        deadline = time.monotonic() + 3.0
        while (
            feed.telemetry.snapshot()["circuit_breakers"] < 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        stop_started = time.monotonic()
        feed.stop()
        assert time.monotonic() - stop_started < 5.0, "stop() blocked on the supervisor cooldown"
        # It tripped once and was cooling down (no re-arm) when stop() hit.
        assert feed.telemetry.snapshot()["circuit_breakers"] == 1


class TestUpdateSymbols:
    def test_update_symbols_swaps_set_and_breaks_active_client(self) -> None:
        """A changed watchlist rebinds the symbol set (normalized + deduped)
        and stops the active client so the feed loop reconnects and
        re-subscribes with the new list."""
        feed, client = _make_feed([])  # constructed for ["NVDA"]
        feed._active_client = client  # simulate a live connection

        changed = feed.update_symbols(["AAPL", "msft", "AAPL"])

        assert changed is True
        assert feed._symbol_set == {"AAPL", "MSFT"}
        assert feed._symbols == ["AAPL", "MSFT"]
        assert client.stopped is True  # in-flight iteration broken -> reconnect

    def test_update_symbols_is_noop_when_set_unchanged(self) -> None:
        feed, client = _make_feed([])  # ["NVDA"]
        feed._active_client = client

        changed = feed.update_symbols(["nvda"])  # same set, different case

        assert changed is False
        assert feed._symbol_set == {"NVDA"}
        assert client.stopped is False  # no needless reconnect

    def test_update_symbols_ignores_empty_universe(self) -> None:
        feed, client = _make_feed([])  # ["NVDA"]
        feed._active_client = client

        assert feed.update_symbols([]) is False
        assert feed.update_symbols(["", "  "]) is False
        assert feed._symbol_set == {"NVDA"}  # never dropped to empty
        assert client.stopped is False

    def test_update_symbols_routes_share_classes_and_filters_unsupported(self) -> None:
        feed, client = _make_feed([])  # constructed for ["NVDA"]
        feed._active_client = client

        changed = feed.update_symbols(["BRK-B", "BF-B", "CTA-PA"])

        assert changed is True
        assert feed._canonical_symbol_set == {"BRK-B", "BF-B"}
        assert feed._symbols == ["BRK.B", "BF.B"]
        assert feed._provider_to_canonical == {
            "BRK.B": "BRK-B",
            "BF.B": "BF-B",
        }
        assert feed.telemetry.snapshot()["symbols_filtered"] == {
            "unsupported_symbol": 1,
        }


class TestReplayStartGatewayWindow:
    """The live gateway refuses replay starts older than roughly one UTC day
    ("Invalid start time. Must be <yesterday 00:00Z> or later"). A cursor
    stranded behind that window — the weekend case: last committed bar is
    Friday's close — must be clamped forward at subscribe time, because a
    refused subscribe delivers no bars and the cursor would otherwise never
    advance again (the 2026-08-16/17 producer reconnect deadlock)."""

    def test_a_weekend_stale_cursor_is_clamped_into_the_window(self) -> None:
        feed, _ = _make_feed([])
        with feed._cache_lock:
            feed._last_committed_ts_event = (
                datetime.now(tz=UTC) - timedelta(days=3)
            ).timestamp()

        start = feed._next_replay_start()

        assert start >= datetime.now(tz=UTC) - timedelta(hours=23, minutes=1)

    def test_a_stale_initial_replay_start_is_clamped_too(self) -> None:
        # No bar ever committed: the candidate is the constructor value,
        # which after a long-running process (or a stale fixture date) can
        # itself lie outside the gateway window.
        feed, _ = _make_feed([])

        start = feed._next_replay_start()

        assert datetime.now(tz=UTC) - _REPLAY_START > timedelta(days=1)
        assert start >= datetime.now(tz=UTC) - timedelta(hours=23, minutes=1)

    def test_a_fresh_cursor_is_returned_unclamped(self) -> None:
        feed, _ = _make_feed([])
        last = datetime.now(tz=UTC) - timedelta(seconds=60)
        with feed._cache_lock:
            feed._last_committed_ts_event = last.timestamp()

        start = feed._next_replay_start()

        assert start == datetime.fromtimestamp(last.timestamp() + 1.0, tz=UTC)

    def test_the_clamp_can_be_disabled_for_fixture_replays(self) -> None:
        feed, _ = _make_feed([], replay_start_max_age=None)

        assert feed._next_replay_start() == _REPLAY_START
