"""Coverage uplift for `open_prep.run_open_prep`.

Targets `main() + Top-N pure helpers` per the bucket-B test plan. Focus is on
helpers that are pure (no FMP / network) and easy to fixture, so we maximise
covered statements per test.

Sections:
- `_extract_time_str` — separator / sentinel / invalid-time edges
- `_macro_relevance_score` — HIGH / MID / LOW / no-match
- `_normalize_cutoff_utc` — HH:MM, HH:MM:SS, invalid inputs
- `_filter_events_by_cutoff_utc` — cutoff filter + untimed include/exclude
- `_sort_macro_events` — impact + preferred-time ordering
- `_format_macro_events` — quality_flags emit, max_events clamp
- `_event_is_today` — ISO + US-style + invalid
- `_parse_symbols` — split / dedupe / blank
- `_compute_tomorrow_outlook` — green / yellow / red traffic-light branches
- `_build_runtime_status` — clean / news_error / quote_failed / atr_missing /
  premarket_error / rate-limit promotion / ATR-coverage stats
- `_parse_args` — defaults via monkeypatched argv
- `main()` — orchestrates `_parse_args` + `generate_open_prep_result` +
  stdout JSON dump
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from open_prep import run_open_prep as rop
from open_prep.run_open_prep import (
    _build_runtime_status,
    _compute_tomorrow_outlook,
    _event_is_today,
    _extract_time_str,
    _filter_events_by_cutoff_utc,
    _format_macro_events,
    _macro_relevance_score,
    _normalize_cutoff_utc,
    _parse_args,
    _parse_symbols,
    _sort_macro_events,
    main,
)

# ---------------------------------------------------------------------------
# _extract_time_str
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("2026-04-23 13:30:00", "13:30:00"),
        ("2026-04-23T13:30:00", "13:30:00"),
        ("2026-04-23T08:15", "08:15:00"),         # HH:MM only → SS=0
        ("2026-04-23", "99:99:99"),                # whole-day sentinel
        ("2026-04-23 99:00:00", "99:99:99"),       # invalid hour → sentinel
        ("2026-04-23 12:99:00", "99:99:99"),       # invalid minute → sentinel
        ("garbled-input", "99:99:99"),
    ],
)
def test_extract_time_str_matrix(input_str: str, expected: str) -> None:
    assert _extract_time_str(input_str) == expected


# ---------------------------------------------------------------------------
# _macro_relevance_score
# ---------------------------------------------------------------------------


def test_macro_relevance_score_buckets() -> None:
    high = _macro_relevance_score("US CPI YoY")
    mid = _macro_relevance_score("Q1 GDP Growth")
    low = _macro_relevance_score("New Home Sales")
    none = _macro_relevance_score("Random unimportant chatter")
    assert high > mid > low >= 0
    assert none == 0


@pytest.mark.parametrize(
    "name",
    ["CPI", "Core PPI", "PCE Index", "Nonfarm Payrolls", "Initial Jobless Claims"],
)
def test_macro_relevance_score_high_tokens(name: str) -> None:
    assert _macro_relevance_score(name) >= rop.MACRO_RELEVANCE_HIGH


# ---------------------------------------------------------------------------
# _normalize_cutoff_utc
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("13:30", "13:30:00"),
        ("13:30:45", "13:30:45"),
        ("00:00:00", "00:00:00"),
        ("23:59:59", "23:59:59"),
    ],
)
def test_normalize_cutoff_utc_happy(input_str: str, expected: str) -> None:
    assert _normalize_cutoff_utc(input_str) == expected


@pytest.mark.parametrize(
    "bad_input",
    [
        "",                # empty
        "13",              # only one part
        "13:30:45:99",     # too many parts
        "ab:cd",           # non-numeric
        "24:00:00",        # hour out of range
        "12:60:00",        # minute out of range
        "12:00:60",        # second out of range
    ],
)
def test_normalize_cutoff_utc_invalid_raises(bad_input: str) -> None:
    with pytest.raises(ValueError):
        _normalize_cutoff_utc(bad_input)


# ---------------------------------------------------------------------------
# _filter_events_by_cutoff_utc
# ---------------------------------------------------------------------------


def test_filter_events_includes_untimed_by_default() -> None:
    events = [
        {"date": "2026-04-23", "event": "Whole-Day Holiday Watch"},
        {"date": "2026-04-23 12:30:00", "event": "CPI"},
        {"date": "2026-04-23 18:00:00", "event": "FOMC Speech"},
    ]
    out = _filter_events_by_cutoff_utc(events, cutoff_utc="14:00:00")
    names = [e["event"] for e in out]
    assert "Whole-Day Holiday Watch" in names
    assert "CPI" in names
    assert "FOMC Speech" not in names


def test_filter_events_drops_untimed_when_disabled() -> None:
    events = [
        {"date": "2026-04-23", "event": "Whole-Day"},
        {"date": "2026-04-23 12:00:00", "event": "Inside"},
    ]
    out = _filter_events_by_cutoff_utc(events, "14:00:00", include_untimed=False)
    names = [e["event"] for e in out]
    assert "Whole-Day" not in names
    assert "Inside" in names


# ---------------------------------------------------------------------------
# _sort_macro_events
# ---------------------------------------------------------------------------


def test_sort_macro_events_high_impact_first() -> None:
    events = [
        {"date": "2026-04-23 14:00:00", "event": "Random Low", "impact": "low"},
        {"date": "2026-04-23 12:30:00", "event": "US CPI", "impact": "high"},
        {"date": "2026-04-23 13:00:00", "event": "Retail Sales", "impact": "medium"},
    ]
    out = _sort_macro_events(events)
    assert out[0]["event"] == "US CPI"
    assert out[-1]["event"] == "Random Low"


def test_sort_macro_events_stable_for_identical_keys() -> None:
    events = [
        {"date": "2026-04-23 12:30:00", "event": "Aaa", "impact": "high"},
        {"date": "2026-04-23 12:30:00", "event": "Bbb", "impact": "high"},
    ]
    out = _sort_macro_events(events)
    assert [e["event"] for e in out] == ["Aaa", "Bbb"]


# ---------------------------------------------------------------------------
# _format_macro_events
# ---------------------------------------------------------------------------


def test_format_macro_events_emits_quality_flags() -> None:
    events = [
        {
            "date": "2026-04-23 12:30:00",
            "event": "CPI",
            "impact": "high",
            "actual": None,        # missing_actual
            "consensus": None,      # missing_consensus
            "unit": "",             # missing_unit
        }
    ]
    out = _format_macro_events(events, max_events=10)
    assert len(out) == 1
    flags = out[0]["data_quality_flags"]
    assert "missing_actual" in flags
    assert "missing_consensus" in flags
    assert "missing_unit" in flags


def test_format_macro_events_respects_max_events_clamp() -> None:
    events = [
        {"date": "2026-04-23", "event": f"E{i}", "impact": "low", "unit": "%", "actual": 1.0, "consensus": 1.0}
        for i in range(20)
    ]
    out = _format_macro_events(events, max_events=5)
    assert len(out) == 5


def test_format_macro_events_zero_max_returns_empty() -> None:
    events = [{"date": "2026-04-23", "event": "X", "unit": "%", "actual": 1.0, "consensus": 1.0}]
    out = _format_macro_events(events, max_events=0)
    assert out == []


# ---------------------------------------------------------------------------
# _event_is_today
# ---------------------------------------------------------------------------


def test_event_is_today_iso_match() -> None:
    today = date(2026, 4, 23)
    assert _event_is_today({"date": "2026-04-23"}, today) is True
    assert _event_is_today({"date": "2026-04-23T12:30:00"}, today) is True
    assert _event_is_today({"date": "2026-04-24"}, today) is False


def test_event_is_today_us_format_match() -> None:
    today = date(2026, 4, 23)
    assert _event_is_today({"date": "04/23/2026"}, today) is True
    assert _event_is_today({"date": "04/23/26"}, today) is True
    assert _event_is_today({"date": "04/24/2026"}, today) is False


def test_event_is_today_invalid_date_returns_false() -> None:
    today = date(2026, 4, 23)
    assert _event_is_today({"date": "garbage"}, today) is False
    assert _event_is_today({"date": ""}, today) is False
    assert _event_is_today({}, today) is False


# ---------------------------------------------------------------------------
# _parse_symbols
# ---------------------------------------------------------------------------


def test_parse_symbols_split_dedupe_uppercase() -> None:
    out = _parse_symbols("aapl, MSFT,aapl ,GOOGL")
    assert out == ["AAPL", "MSFT", "GOOGL"]


def test_parse_symbols_blank_returns_empty() -> None:
    assert _parse_symbols("") == []
    assert _parse_symbols("   ") == []
    assert _parse_symbols(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _compute_tomorrow_outlook — traffic-light branches
# ---------------------------------------------------------------------------


def _is_trading_day_stub(d: date) -> bool:
    return True  # treat every day as a trading day for deterministic tests


def test_compute_tomorrow_outlook_green_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rop, "_is_us_equity_trading_day", _is_trading_day_stub)
    today = date(2026, 4, 22)
    out = _compute_tomorrow_outlook(
        today=today,
        macro_bias=0.5,
        earnings_calendar=[],
        ranked=[{"long_allowed": True}, {"long_allowed": True}],
        all_range_events=[],
    )
    assert out["next_trading_day"] == "2026-04-23"
    assert out["outlook_color"] == "green"
    assert "macro_bias_positive" in out["reasons"]


def test_compute_tomorrow_outlook_red_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rop, "_is_us_equity_trading_day", _is_trading_day_stub)
    today = date(2026, 4, 22)
    out = _compute_tomorrow_outlook(
        today=today,
        macro_bias=-0.75,                  # strongly negative → -2.0
        earnings_calendar=[],
        ranked=[{"long_allowed": False}, {"long_allowed": False}, {"long_allowed": True}],
        all_range_events=[
            {"date": "2026-04-23", "impact": "high", "event": "FOMC"},
            {"date": "2026-04-23", "impact": "high", "event": "CPI"},
        ],
    )
    assert out["outlook_color"] == "red"
    assert out["high_impact_events_tomorrow"] == 2
    assert any(r.startswith("high_impact_events_") for r in out["reasons"])


def test_compute_tomorrow_outlook_yellow_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rop, "_is_us_equity_trading_day", _is_trading_day_stub)
    out = _compute_tomorrow_outlook(
        today=date(2026, 4, 22),
        macro_bias=0.0,
        earnings_calendar=[],
        ranked=[{"long_allowed": True}],
        all_range_events=[],
    )
    assert out["outlook_color"] == "orange"
    assert "macro_bias_neutral" in out["reasons"]


def test_compute_tomorrow_outlook_skips_non_trading_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Skip Apr 23 (treat as holiday); next valid day is Apr 24.
    def stub(d: date) -> bool:
        return d != date(2026, 4, 23)

    monkeypatch.setattr(rop, "_is_us_equity_trading_day", stub)
    out = _compute_tomorrow_outlook(
        today=date(2026, 4, 22),
        macro_bias=0.0,
        earnings_calendar=[],
        ranked=[],
        all_range_events=[],
    )
    assert out["next_trading_day"] == "2026-04-24"


def test_compute_tomorrow_outlook_heavy_earnings_bmo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rop, "_is_us_equity_trading_day", _is_trading_day_stub)
    next_td = "2026-04-23"
    earnings = [
        {"date": next_td, "earnings_timing": "BMO", "symbol": f"S{i}"}
        for i in range(15)
    ]
    out = _compute_tomorrow_outlook(
        today=date(2026, 4, 22),
        macro_bias=0.0,
        earnings_calendar=earnings,
        ranked=[],
        all_range_events=[],
    )
    assert out["earnings_bmo_tomorrow_count"] == 15
    assert any(r.startswith("heavy_earnings_bmo_") for r in out["reasons"])


# ---------------------------------------------------------------------------
# _build_runtime_status
# ---------------------------------------------------------------------------


def test_build_runtime_status_clean() -> None:
    out = _build_runtime_status(news_fetch_error=None, atr_fetch_errors={})
    assert out["degraded_mode"] is False
    assert out["fatal_stage"] is None
    assert out["warnings"] == []
    assert out["atr_telemetry"]["atr_candidate_count"] == 0
    assert out["atr_telemetry"]["atr_missing_rate_pct"] == 0.0


def test_build_runtime_status_news_error() -> None:
    out = _build_runtime_status(news_fetch_error="benzinga 503", atr_fetch_errors={})
    assert out["degraded_mode"] is True
    assert any(w["stage"] == "news_fetch" for w in out["warnings"])


def test_build_runtime_status_quote_partial_promotes_partial_data() -> None:
    diag = {
        "failed_quote_symbols": ["AAPL", "MSFT"],
        "partial_quote_fetch": True,
        "quote_fetch_error_summary": "2/10 symbols failed",
    }
    out = _build_runtime_status(
        news_fetch_error=None,
        atr_fetch_errors={},
        quote_fetch_diagnostics=diag,
    )
    quote_w = next(w for w in out["warnings"] if w["stage"] == "quote_fetch")
    assert quote_w["code"] == "PARTIAL_DATA"
    assert quote_w["symbols"] == ["AAPL", "MSFT"]


def test_build_runtime_status_atr_missing_with_coverage_pct() -> None:
    out = _build_runtime_status(
        news_fetch_error=None,
        atr_fetch_errors={"AAPL": "503", "MSFT": "timeout"},
        atr_candidate_symbols=["AAPL", "MSFT", "GOOGL", "AMZN"],
    )
    atr_t = out["atr_telemetry"]
    assert atr_t["atr_candidate_count"] == 4
    assert atr_t["atr_missing_count"] == 2
    assert atr_t["atr_available_count"] == 2
    assert atr_t["atr_missing_rate_pct"] == 50.0
    assert any(w["stage"] == "atr_fetch" for w in out["warnings"])


def test_build_runtime_status_premarket_error() -> None:
    out = _build_runtime_status(
        news_fetch_error=None,
        atr_fetch_errors={},
        premarket_fetch_error="API down",
    )
    assert any(w["stage"] == "premarket_fetch" for w in out["warnings"])


def test_build_runtime_status_rate_limit_promotion() -> None:
    out = _build_runtime_status(
        news_fetch_error="429 too many requests",
        atr_fetch_errors={},
    )
    news_w = next(w for w in out["warnings"] if w["stage"] == "news_fetch")
    assert news_w["code"] == "RATE_LIMIT"


def test_build_runtime_status_atr_filter_skips_dunder_keys() -> None:
    out = _build_runtime_status(
        news_fetch_error=None,
        atr_fetch_errors={"__error__": "x", "AAPL": "y"},
        atr_candidate_symbols=["AAPL"],
    )
    atr_t = out["atr_telemetry"]
    assert atr_t["atr_missing_symbols"] == ["AAPL"]


def test_build_runtime_status_fatal_stage_is_passed_through() -> None:
    out = _build_runtime_status(
        news_fetch_error=None,
        atr_fetch_errors={},
        fatal_stage="news_fetch",
    )
    assert out["fatal_stage"] == "news_fetch"


# ---------------------------------------------------------------------------
# _parse_args (defaults via monkeypatched argv)
# ---------------------------------------------------------------------------


def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["run_open_prep"])
    ns = _parse_args()
    assert ns.symbols == ""
    assert ns.days_ahead == 3
    assert ns.top == 10
    assert ns.trade_cards == 5
    assert ns.max_macro_events == 15
    assert ns.pre_open_only is False
    assert ns.pre_open_cutoff_utc == "16:00:00"
    assert ns.atr_period == 14


def test_parse_args_with_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_open_prep",
            "--symbols", "aapl,msft",
            "--top", "25",
            "--trade-cards", "10",
            "--days-ahead", "5",
            "--pre-open-only",
            "--pre-open-cutoff-utc", "12:00:00",
        ],
    )
    ns = _parse_args()
    assert ns.symbols == "aapl,msft"
    assert ns.top == 25
    assert ns.trade_cards == 10
    assert ns.days_ahead == 5
    assert ns.pre_open_only is True
    assert ns.pre_open_cutoff_utc == "12:00:00"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_invokes_generator_and_writes_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_generate(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"ok": True, "candidates": ["AAPL"]}

    monkeypatch.setattr(rop, "generate_open_prep_result", fake_generate)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_open_prep",
            "--symbols", "aapl",
            "--top", "3",
            "--trade-cards", "2",
        ],
    )

    main()

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed == {"ok": True, "candidates": ["AAPL"]}

    # main() converted symbols, normalised universe_source/gap_scope to upper,
    # and clamped the integer args.
    assert captured["symbols"] == ["AAPL"]
    assert captured["top"] == 3
    assert captured["trade_cards"] == 2
    assert captured["fmp_min_market_cap"] >= 1
    assert captured["fmp_max_symbols"] >= 1
    assert captured["mover_seed_max_symbols"] >= 0
    assert captured["analyst_catalyst_limit"] >= 0
    # Universe source upper-cased
    assert captured["universe_source"].isupper()
    assert captured["gap_scope"].isupper()


def test_main_clamps_negative_int_args(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_generate(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(rop, "generate_open_prep_result", fake_generate)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_open_prep",
            "--fmp-min-market-cap", "-1",
            "--fmp-max-symbols", "-5",
            "--mover-seed-max-symbols", "-3",
            "--analyst-catalyst-limit", "-2",
        ],
    )
    main()
    capsys.readouterr()  # discard
    assert captured["fmp_min_market_cap"] == 1
    assert captured["fmp_max_symbols"] == 1
    assert captured["mover_seed_max_symbols"] == 0
    assert captured["analyst_catalyst_limit"] == 0
