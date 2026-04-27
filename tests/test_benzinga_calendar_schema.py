"""Pin canonical Benzinga calendar normalization (Lane 15)."""
from newsstack_fmp.normalize import normalize_benzinga_calendar_item


def test_canonical_keys_from_originals():
    raw = {"id": "abc", "date": "2026-04-27", "ticker": "AAPL",
           "actual": 1.5, "forecast": 1.4, "previous": 1.3, "importance": 4}
    out = normalize_benzinga_calendar_item(raw, "earnings")
    assert out["event_id"] == "abc"
    assert out["event_date"] == "2026-04-27"
    assert out["symbol"] == "AAPL"
    assert out["event_actual"] == 1.5
    assert out["event_forecast"] == 1.4
    assert out["event_previous"] == 1.3
    assert out["importance"] == 4
    assert out["kind"] == "earnings"
    assert out["actual"] == 1.5
    assert out["ticker"] == "AAPL"


def test_canonical_keys_from_renamed_aliases():
    raw = {"uuid": "xyz", "datetime": "2026-04-27T12:00",
           "symbol": "MSFT", "actualValue": 2.0,
           "forecastValue": 1.9, "previousValue": 1.8, "impact": 3}
    out = normalize_benzinga_calendar_item(raw, "earnings")
    assert out["event_id"] == "xyz"
    assert out["event_date"] == "2026-04-27T12:00"
    assert out["symbol"] == "MSFT"
    assert out["event_actual"] == 2.0
    assert out["event_forecast"] == 1.9
    assert out["event_previous"] == 1.8
    assert out["importance"] == 3


def test_missing_variants_yield_none():
    out = normalize_benzinga_calendar_item({"id": "x"}, "ratings")
    assert out["event_id"] == "x"
    assert out["event_actual"] is None
    assert out["event_forecast"] is None
    assert out["kind"] == "ratings"


def test_non_dict_input_safe():
    out = normalize_benzinga_calendar_item("not a dict", "ratings")
    assert out["kind"] == "ratings"
    assert out["raw"] == "not a dict"
