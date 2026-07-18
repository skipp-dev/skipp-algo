from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from newsstack_fmp import ingest_opra_options_flow as module


class _Store:
    def __init__(self, rows):
        self._rows = rows

    def to_df(self):
        return pd.DataFrame(self._rows)


class _Provider:
    def __init__(self, available_end: datetime):
        self.available_end = pd.Timestamp(available_end)
        self.calls: list[dict] = []

    def get_schema_available_end(self, dataset: str, schema: str):
        assert dataset == "OPRA.PILLAR"
        return self.available_end

    def get_range(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["schema"] == "trades":
            return _Store(
                [
                    {
                        "instrument_id": 1,
                        "ts_event": int(self.available_end.timestamp() * 1e9),
                        "price": 3.0,
                        "size": 100,
                        "side": "B",
                    }
                ]
            )
        return _Store(
            [
                {
                    "instrument_id": 1,
                    "underlying": "AAPL",
                    "strike_price": 200,
                    "expiration": "2026-07-24",
                    "instrument_class": "C",
                    "raw_symbol": "AAPL  260724C00200000",
                }
            ]
        )


def test_too_fresh_historical_window_does_not_pretend_to_be_live(monkeypatch) -> None:
    now = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
    provider = _Provider(datetime(2026, 7, 18, 14, 0, tzinfo=UTC))
    monkeypatch.setattr(module, "_utc_now", lambda: now)
    monkeypatch.setattr(module, "_make_provider", lambda _key: provider)
    assert module.fetch_opra_options_flow("", "AAPL", window_minutes=15) == []
    assert provider.calls == []


def test_definition_request_is_utc_day_aligned_and_cached(monkeypatch) -> None:
    module._DEFINITION_CACHE.clear()
    now = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
    provider = _Provider(datetime(2026, 7, 18, 14, 55, tzinfo=UTC))
    monkeypatch.setattr(module, "_utc_now", lambda: now)
    monkeypatch.setattr(module, "_make_provider", lambda _key: provider)
    first = module.fetch_opra_options_flow("", "AAPL", window_minutes=15)
    second = module.fetch_opra_options_flow("", "AAPL", window_minutes=15)
    assert first and second
    definition_calls = [call for call in provider.calls if call["schema"] == "definition"]
    assert len(definition_calls) == 1
    assert definition_calls[0]["start"] == "2026-07-18T00:00:00"
