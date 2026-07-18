from __future__ import annotations

import json
from unittest.mock import Mock

from databento_client import _databento_get_range_with_retry
from databento_usage import DatabentoUsageRecorder


def test_historical_and_live_are_separate_low_cardinality_series() -> None:
    recorder = DatabentoUsageRecorder()
    recorder.record(
        dataset="EQUS.MINI",
        schema="ohlcv-1m",
        mode="historical",
        consumer="test",
        external_requests=1,
        symbols_requested=2,
    )
    recorder.record(
        dataset="EQUS.MINI",
        schema="ohlcv-1m",
        mode="live",
        consumer="test",
        subscriptions=1,
        symbols_requested=2,
        records=1,
    )
    values = list(recorder.snapshot().values())
    assert {value["mode"] for value in values} == {"historical", "live"}
    assert sum(value["external_requests"] for value in values) == 1
    assert sum(value["subscriptions"] for value in values) == 1


def test_unknown_measurements_remain_null_and_cache_hit_is_not_request() -> None:
    recorder = DatabentoUsageRecorder()
    recorder.record(
        dataset="OPRA.PILLAR",
        schema="tcbbo",
        mode="live",
        consumer="opra-shadow",
        cache_hits=1,
    )
    slot = next(iter(recorder.snapshot().values()))
    assert slot["external_requests"] == 0
    assert slot["records"] is None
    assert slot["bytes"] is None


def test_flush_accumulates_monthly_series_atomically(tmp_path) -> None:
    path = tmp_path / "databento_usage.json"
    recorder = DatabentoUsageRecorder()
    for _ in range(2):
        recorder.record(
            dataset="OPRA.PILLAR",
            schema="tcbbo",
            mode="live",
            consumer="opra-shadow",
            records=3,
            candidates=1,
        )
    assert recorder.flush(path, month="2026-07", now_iso="2026-07-18T00:00:00Z")
    payload = json.loads(path.read_text(encoding="utf-8"))
    slot = next(iter(payload["months"]["2026-07"]["series"].values()))
    assert payload["version"] == "databento-usage/v1"
    assert slot["records"] == 6
    assert slot["candidates"] == 2


def test_historical_wrapper_emits_one_external_request(monkeypatch) -> None:
    events: list[dict] = []
    monkeypatch.setattr("databento_usage.record", lambda **kwargs: events.append(kwargs))
    client = Mock()
    client.timeseries.get_range.return_value = object()
    _databento_get_range_with_retry(
        client,
        context="unit-test",
        max_attempts=1,
        dataset="EQUS.MINI",
        schema="ohlcv-1m",
        symbols=["AAPL", "MSFT"],
        start="2026-07-17",
        end="2026-07-18",
    )
    assert len(events) == 1
    assert events[0]["external_requests"] == 1
    assert events[0]["symbols_requested"] == 2
    assert events[0]["mode"] == "historical"
