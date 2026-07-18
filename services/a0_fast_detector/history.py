"""Databento Historical provider for fail-closed A0 session reconstruction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from databento_client import _databento_get_range_with_retry, _make_databento_client
from open_prep.a0_stream import DatabentoOhlcv1sAdapter
from open_prep.a0_stream_recovery import HistoricalBootstrapBatch
from open_prep.a0_stream_state import StreamBar

# An in-window response with zero bars is a legitimately quiet symbol only over a
# short window; beyond this many seconds of regular session, an empty fetch is a
# fault (e.g. a 200-empty response) and must not be trusted as full coverage.
_MAX_EMPTY_COVERAGE_WINDOW_SECONDS = 300.0


class DatabentoHistoricalBarsProvider:
    def __init__(self, api_key: str, *, dataset: str = "EQUS.MINI") -> None:
        self._client = _make_databento_client(api_key)
        self._dataset = dataset
        self._adapter = DatabentoOhlcv1sAdapter()

    def fetch_before(self, bar: StreamBar) -> HistoricalBootstrapBatch:
        event = datetime.fromtimestamp(bar.ts_event, UTC)
        event_et = event.astimezone(ZoneInfo("America/New_York"))
        session_open = event_et.replace(hour=9, minute=30, second=0, microsecond=0)
        start = session_open.astimezone(UTC)
        end = event
        store = _databento_get_range_with_retry(
            self._client,
            context=f"a0_fast_recovery:{bar.symbol}",
            dataset=self._dataset,
            schema="ohlcv-1s",
            symbols=[bar.symbol],
            stype_in="raw_symbol",
            start=start.isoformat(),
            end=end.isoformat(),
        )
        bars = tuple(self._normalize_records(store, bar.symbol))
        request_start = start.timestamp()
        request_end = end.timestamp()
        # Completeness rests on Databento get_range's contract (it returns the
        # full requested window or raises). We reject a *misranged* fetch — any
        # bar outside [request_start, request_end) — and, as defence in depth, an
        # empty response over a window too long to be a genuinely quiet symbol
        # (a 200-empty fault mid-session would otherwise reconstruct volume as
        # zero). A short empty window (quiet open) stays covered; OHLCV-1s emits
        # bars only for active seconds, so a sparse in-window response has no
        # per-second expected count to check.
        in_window = all(
            request_start <= record.ts_event < request_end for record in bars
        )
        empty_over_long_window = (
            not bars
            and request_end - request_start > _MAX_EMPTY_COVERAGE_WINDOW_SECONDS
        )
        coverage_complete = in_window and not empty_over_long_window
        return HistoricalBootstrapBatch(
            symbol=bar.symbol,
            request_start=request_start,
            request_end=request_end,
            coverage_complete=coverage_complete,
            bars=bars,
        )

    def _normalize_records(self, store: Any, symbol: str) -> list[StreamBar]:
        bars: list[StreamBar] = []
        for record in store:
            record_type = type(record).__name__.upper()
            if "OHLCV" not in record_type and "BAR" not in record_type:
                continue
            bars.append(self._adapter.normalize(record, symbol=symbol))
        return bars
