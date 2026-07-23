"""Tests for the A1 multi-horizon outcome pipeline (60m / 120m / EOD).

Covers the three things the horizon extension must get right:

1. **Backward compatibility** — the legacy ``pnl_30m_pct`` /
   ``profitable_30m`` fields keep their exact names, their long-only
   semantics and their 09:30-anchored window for pre-open capsules.
2. **``fired_at`` anchoring** — an intraday real-time signal is measured
   from its own fire time, not from the 09:30 market open.
3. **Per-horizon completeness guards** — a horizon whose window is
   truncated (or runs past the RTH close) stays ``None`` instead of
   carrying a short window mislabelled as the full horizon.
"""
from __future__ import annotations

from datetime import date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo as _ZoneInfo

import pandas as pd
import pytest

from open_prep.outcome_backfill import (
    _fetch_bars,
    _fetch_end_time,
    _resolve_anchor,
    backfill_outcomes,
    build_parser,
    compute_pnl_from_bars,
)
from open_prep.outcomes import (
    DEFAULT_HORIZON,
    HORIZON_KEYS,
    OUTCOME_HORIZONS,
    compute_hit_rates,
    get_horizon,
    get_symbol_hit_rate,
    horizon_fields,
)

_ET = _ZoneInfo("America/New_York")
_UTC = _ZoneInfo("UTC")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _rth_bars(
    symbol: str,
    run_date: date,
    price_at: Any,
    *,
    start: dt_time = dt_time(9, 30),
    end: dt_time = dt_time(16, 0),
) -> pd.DataFrame:
    """Build a full-RTH 1-min OHLCV frame; ``price_at(minute_index)`` sets price."""
    rows: list[dict[str, Any]] = []
    cur = datetime.combine(run_date, start, tzinfo=_ET)
    stop = datetime.combine(run_date, end, tzinfo=_ET)
    idx = 0
    while cur < stop:
        price = float(price_at(idx))
        rows.append({
            "symbol": symbol,
            "ts_event": cur.astimezone(_UTC),
            "open": price,
            "high": price + 0.01,
            "low": price - 0.01,
            "close": price,
            "volume": 1000,
        })
        cur = cur.replace()  # no-op; advance below
        cur = cur + pd.Timedelta(minutes=1).to_pytimedelta()
        idx += 1
    return pd.DataFrame(rows)


def _flat_then_step(step_minute: int, base: float, after: float) -> Any:
    """Price is *base* until *step_minute*, then *after* (minute index from 09:30)."""
    return lambda i: base if i < step_minute else after


def _halted_bars(symbol: str, run_date: date) -> pd.DataFrame:
    """A mid-day trading halt: bars 09:30-11:03, nothing until 12:30, then to 16:00.

    Anchored at 11:00 this is the realistic "partial" tape — the 30 m and
    60 m windows contain almost no prints, while 120 m and EOD are fully
    measurable.
    """
    early = _rth_bars(symbol, run_date, lambda i: 100.0 + i * 0.01, end=dt_time(11, 3))
    late = _rth_bars(
        symbol, run_date, lambda i: 120.0 + i * 0.01, start=dt_time(12, 30),
    )
    return pd.concat([early, late], ignore_index=True)


# ── Horizon catalogue ───────────────────────────────────────────────────────


class TestHorizonCatalogue:
    def test_keys_cover_30_60_120_eod(self) -> None:
        assert HORIZON_KEYS == ("30m", "60m", "120m", "eod")
        assert DEFAULT_HORIZON == "30m"

    def test_legacy_field_names_are_preserved(self) -> None:
        """The 30m horizon must map onto the EXACT legacy field names."""
        assert horizon_fields("30m") == {
            "pnl": "pnl_30m_pct",
            "pnl_signed": "pnl_30m_pct_signed",
            "profitable": "profitable_30m",
            "profitable_directional": "profitable_30m_directional",
        }

    def test_extended_field_names(self) -> None:
        assert horizon_fields("60m")["pnl"] == "pnl_60m_pct"
        assert horizon_fields("120m")["profitable"] == "profitable_120m"
        assert horizon_fields("eod")["pnl"] == "pnl_eod_pct"
        assert horizon_fields("eod")["profitable_directional"] == "profitable_eod_directional"

    def test_eod_has_no_fixed_minute_length(self) -> None:
        assert get_horizon("eod").minutes is None
        assert get_horizon("60m").minutes == 60

    def test_min_window_scales_with_horizon(self) -> None:
        # The 30m floor must stay at its legacy value or existing labels shift.
        assert get_horizon("30m").min_window_min == 25
        for h in OUTCOME_HORIZONS:
            if h.minutes is not None:
                assert h.min_window_min < h.minutes

    def test_unknown_horizon_raises(self) -> None:
        with pytest.raises(ValueError):
            get_horizon("45m")
        with pytest.raises(ValueError):
            horizon_fields("45m")


# ── Multi-horizon PnL ───────────────────────────────────────────────────────


class TestMultiHorizonPnl:
    def test_all_horizons_resolved_from_full_day(self) -> None:
        d = date(2026, 4, 17)
        # 100 at the open; +1 per 30-min block so each horizon differs.
        def price(i: int) -> float:
            return 100.0 + (i // 30)

        df = _rth_bars("MULTI", d, price)
        res = compute_pnl_from_bars(df, "MULTI", d)
        assert res is not None
        # 09:30 open = 100. 09:59 close = 100 (block 0) -> 0.0 %
        assert res["pnl_30m_pct"] == pytest.approx(0.0, abs=1e-6)
        # 10:29 close = 101 (block 1) -> +1 %
        assert res["pnl_60m_pct"] == pytest.approx(1.0, abs=1e-6)
        # 11:29 close = 103 (block 3) -> +3 %
        assert res["pnl_120m_pct"] == pytest.approx(3.0, abs=1e-6)
        # 15:59 close = 112 (block 12) -> +12 %
        assert res["pnl_eod_pct"] == pytest.approx(12.0, abs=1e-6)
        assert res["profitable_eod"] is True
        assert set(res["outcome_horizons_resolved"]) == {"30m", "60m", "120m", "eod"}

    def test_legacy_30m_fields_unchanged_on_legacy_window(self) -> None:
        """A 09:30-10:00-only frame still yields the legacy 30m label."""
        d = date(2026, 4, 17)
        df = _rth_bars("LEG", d, lambda i: 100.0 + i * (3.0 / 29), end=dt_time(10, 0))
        res = compute_pnl_from_bars(df, "LEG", d)
        assert res is not None
        assert res["profitable_30m"] is True
        assert res["pnl_30m_pct"] == pytest.approx(3.0, abs=0.01)
        # Longer horizons have no bars -> honest None, never fabricated 0.
        assert res["pnl_60m_pct"] is None
        assert res["profitable_60m"] is None
        assert res["pnl_eod_pct"] is None

    def test_direction_signs_every_horizon(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("SHRT", d, lambda i: 100.0 - (i // 30))
        res = compute_pnl_from_bars(df, "SHRT", d, direction="short")
        assert res is not None
        for key in ("30m", "60m", "120m", "eod"):
            f = horizon_fields(key)
            raw = res[f["pnl"]]
            assert raw is not None
            assert res[f["pnl_signed"]] == pytest.approx(-raw, abs=1e-6)
        # A falling tape is a WINNING short on the long horizons.
        assert res["profitable_eod"] is False          # long-only view
        assert res["profitable_eod_directional"] is True  # trade-intent view

    def test_requested_horizon_subset_emits_only_those_fields(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("SUB", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(df, "SUB", d, horizons=("30m", "eod"))
        assert res is not None
        assert "pnl_30m_pct" in res
        assert "pnl_eod_pct" in res
        assert "pnl_60m_pct" not in res
        assert "pnl_120m_pct" not in res

    def test_non_finite_price_keeps_every_horizon_unresolved(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("BAD", d, lambda i: float("inf") if i == 0 else 100.0)
        assert compute_pnl_from_bars(df, "BAD", d) is None


# ── fired_at anchoring ──────────────────────────────────────────────────────


class TestFiredAtAnchoring:
    def test_intraday_signal_measures_from_fired_at(self) -> None:
        """An 11:00 signal must NOT be scored on the 09:30-10:00 span."""
        d = date(2026, 4, 17)
        # Flat 100 all morning, jumps to 110 at 11:00 (minute index 90).
        df = _rth_bars("RT", d, _flat_then_step(90, 100.0, 110.0))
        anchored = compute_pnl_from_bars(
            df, "RT", d, fired_at="2026-04-17T11:00:00-04:00",
        )
        assert anchored is not None
        assert anchored["outcome_anchor"] == "fired_at"
        # Entry = the 11:00 bar open (110), exit 11:29 close (110) -> 0 %.
        assert anchored["pnl_30m_pct"] == pytest.approx(0.0, abs=1e-6)

        # The same tape anchored at the open would have reported +10 % by EOD
        # and 0 % at 30m; the point is the ANCHOR moved, not the arithmetic.
        at_open = compute_pnl_from_bars(df, "RT", d)
        assert at_open is not None
        assert at_open["outcome_anchor"] == "market_open"
        assert at_open["pnl_eod_pct"] == pytest.approx(10.0, abs=1e-6)
        assert anchored["pnl_eod_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_fired_at_window_is_relative_not_absolute(self) -> None:
        d = date(2026, 4, 17)
        # Flat 100 until 11:30 (index 120), then 105.
        df = _rth_bars("STEP", d, _flat_then_step(120, 100.0, 105.0))
        res = compute_pnl_from_bars(
            df, "STEP", d, fired_at="2026-04-17T11:00:00-04:00",
        )
        assert res is not None
        # 30m window 11:00->11:30 ends BEFORE the step: 0 %.
        assert res["pnl_30m_pct"] == pytest.approx(0.0, abs=1e-6)
        # 60m window 11:00->12:00 contains it: +5 %.
        assert res["pnl_60m_pct"] == pytest.approx(5.0, abs=1e-6)

    def test_pre_open_capsule_keeps_market_open_anchor(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("PRE", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(df, "PRE", d, fired_at=None)
        assert res is not None
        assert res["outcome_anchor"] == "market_open"
        assert res["outcome_anchor_et"].startswith("2026-04-17T09:30:00")

    def test_premarket_fired_at_clamps_to_the_open(self) -> None:
        """A 07:15 fire cannot be measured on bars we do not fetch."""
        d = date(2026, 4, 17)
        df = _rth_bars("EARLY", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(
            df, "EARLY", d, fired_at="2026-04-17T07:15:00-04:00",
        )
        assert res is not None
        assert res["outcome_anchor"] == "market_open"

    def test_fired_at_on_a_different_date_falls_back_to_the_open(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("MISMATCH", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(
            df, "MISMATCH", d, fired_at="2026-04-16T11:00:00-04:00",
        )
        assert res is not None
        assert res["outcome_anchor"] == "market_open"

    def test_fired_at_accepts_epoch_seconds(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("EPOCH", d, _flat_then_step(90, 100.0, 110.0))
        epoch = datetime.combine(d, dt_time(11, 0), tzinfo=_ET).timestamp()
        res = compute_pnl_from_bars(df, "EPOCH", d, fired_at=epoch)
        assert res is not None
        assert res["outcome_anchor"] == "fired_at"
        assert res["outcome_anchor_et"].startswith("2026-04-17T11:00:00")

    def test_unparseable_fired_at_falls_back_to_the_open(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("JUNK", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(df, "JUNK", d, fired_at="not-a-timestamp")
        assert res is not None
        assert res["outcome_anchor"] == "market_open"

    def test_resolve_anchor_reports_source(self) -> None:
        d = date(2026, 4, 17)
        anchor, source = _resolve_anchor("2026-04-17T13:05:00-04:00", d)
        assert source == "fired_at"
        assert anchor.hour == 13 and anchor.minute == 5
        anchor, source = _resolve_anchor(None, d)
        assert source == "market_open"
        assert anchor.hour == 9 and anchor.minute == 30


# ── Per-horizon completeness guards ─────────────────────────────────────────


class TestPerHorizonGuards:
    def test_halted_tape_resolves_only_the_horizons_it_covers(self) -> None:
        """A halt right after the fire kills 30m/60m but leaves 120m + EOD."""
        d = date(2026, 4, 17)
        df = _halted_bars("HALTED", d)
        res = compute_pnl_from_bars(
            df, "HALTED", d, fired_at="2026-04-17T11:00:00-04:00",
        )
        assert res is not None
        assert res["profitable_30m"] is None
        assert res["pnl_30m_pct"] is None
        assert res["pnl_60m_pct"] is None
        assert res["pnl_120m_pct"] is not None
        assert res["pnl_eod_pct"] is not None
        assert res["outcome_horizons_resolved"] == ["120m", "eod"]

    def test_signal_too_late_for_any_horizon_returns_none(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("TOOLATE", d, lambda i: 100.0 + i * 0.01)
        assert compute_pnl_from_bars(
            df, "TOOLATE", d, fired_at="2026-04-17T15:50:00-04:00",
        ) is None

    def test_late_but_complete_signal_still_gets_its_30m(self) -> None:
        """15:20 + 30 min still fits the session — the guard must not over-reject."""
        d = date(2026, 4, 17)
        df = _rth_bars("LATE", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(
            df, "LATE", d, fired_at="2026-04-17T15:20:00-04:00",
        )
        assert res is not None
        assert res["pnl_30m_pct"] is not None
        assert res["pnl_60m_pct"] is None   # 16:20 is past the close
        assert res["pnl_eod_pct"] is not None

    def test_eod_needs_a_print_near_the_close(self) -> None:
        """Bars stopping at 14:00 must not be labelled as the EOD outcome."""
        d = date(2026, 4, 17)
        df = _rth_bars("HALT", d, lambda i: 100.0 + i * 0.01, end=dt_time(14, 0))
        res = compute_pnl_from_bars(df, "HALT", d)
        assert res is not None
        assert res["pnl_120m_pct"] is not None
        assert res["pnl_eod_pct"] is None
        assert res["profitable_eod"] is None

    def test_truncated_60m_window_stays_none(self) -> None:
        d = date(2026, 4, 17)
        # Bars only to 10:15: 30m complete, 60m needs a print at/after 10:20.
        df = _rth_bars("SHORT", d, lambda i: 100.0 + i * 0.01, end=dt_time(10, 15))
        res = compute_pnl_from_bars(df, "SHORT", d)
        assert res is not None
        assert res["pnl_30m_pct"] is not None
        assert res["pnl_60m_pct"] is None

    def test_late_entry_bar_still_kills_every_horizon(self) -> None:
        """The shared entry guard is unchanged: no entry -> no outcome at all."""
        d = date(2026, 4, 17)
        df = _rth_bars("OPENHALT", d, lambda i: 100.0 + i * 0.01, start=dt_time(9, 52))
        assert compute_pnl_from_bars(df, "OPENHALT", d) is None

    def test_triple_barrier_stays_tied_to_the_primary_horizon(self) -> None:
        d = date(2026, 4, 17)
        df = _rth_bars("TB", d, lambda i: 100.0 + i * 0.01)
        res = compute_pnl_from_bars(df, "TB", d)
        assert res is not None
        assert res["label_tb"] is not None
        # 30m unresolved -> no triple-barrier label either (never fabricated).
        halted = compute_pnl_from_bars(
            _halted_bars("TB", d), "TB", d, fired_at="2026-04-17T11:00:00-04:00",
        )
        assert halted is not None
        assert halted["label_tb"] is None
        assert halted["profitable_tb"] is None
        assert halted["tb_barrier_source"] is None


# ── Fetch window ────────────────────────────────────────────────────────────


class TestFetchWindow:
    def test_extended_horizons_widen_the_window_to_the_close(self) -> None:
        assert _fetch_end_time(("30m", "60m"), has_intraday_anchor=False) == dt_time(16, 1)
        assert _fetch_end_time(("30m", "eod"), has_intraday_anchor=False) == dt_time(16, 1)

    def test_legacy_30m_only_keeps_the_narrow_window(self) -> None:
        assert _fetch_end_time(("30m",), has_intraday_anchor=False) == dt_time(10, 1)

    def test_intraday_anchor_widens_even_for_30m_only(self) -> None:
        assert _fetch_end_time(("30m",), has_intraday_anchor=True) == dt_time(16, 1)

    def test_fetch_bars_passes_the_widened_end(self) -> None:
        d = date(2026, 4, 17)
        store = MagicMock()
        store.to_df.return_value = pd.DataFrame({"x": [1]})
        provider = MagicMock()
        provider.get_range.return_value = store
        _fetch_bars(provider, ["NVDA"], d, end_time=dt_time(16, 1))
        kwargs = provider.get_range.call_args.kwargs
        assert kwargs["end"].startswith("2026-04-17T16:01")
        assert kwargs["start"].startswith("2026-04-17T09:29")


# ── backfill_outcomes wiring ────────────────────────────────────────────────


def _write_outcomes(tmp_path: Path, run_date: date, records: list[dict[str, Any]]) -> Path:
    out_dir = tmp_path / "artifacts" / "open_prep" / "outcomes"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"outcomes_{run_date.isoformat()}.json"
    import json

    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return path


class TestBackfillWiring:
    def test_writes_every_horizon_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        import open_prep.outcome_backfill as mod

        d = date(2026, 4, 17)
        path = _write_outcomes(tmp_path, d, [
            {"symbol": "NVDA", "date": d.isoformat(), "profitable_30m": None,
             "pnl_30m_pct": None, "direction": "long"},
        ])
        monkeypatch.setattr(mod, "OUTCOMES_DIR", path.parent)
        monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)

        df = _rth_bars("NVDA", d, lambda i: 100.0 + i * 0.01)
        store = MagicMock()
        store.to_df.return_value = df
        provider = MagicMock()
        provider.get_range.return_value = store

        summary = backfill_outcomes(target_dates=[d], provider=provider)
        assert summary["resolved"] == 1

        rec = json.loads(path.read_text(encoding="utf-8"))[0]
        assert rec["profitable_30m"] is True
        for key in HORIZON_KEYS:
            f = horizon_fields(key)
            assert rec[f["pnl"]] is not None, key
            assert rec[f["profitable"]] is not None, key
        assert rec["outcome_anchor"] == "market_open"

    def test_fired_at_record_is_anchored_at_its_fire_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        import open_prep.outcome_backfill as mod

        d = date(2026, 4, 17)
        path = _write_outcomes(tmp_path, d, [
            {"symbol": "RT", "date": d.isoformat(), "profitable_30m": None,
             "pnl_30m_pct": None, "direction": "long",
             "fired_at": "2026-04-17T11:00:00-04:00"},
        ])
        monkeypatch.setattr(mod, "OUTCOMES_DIR", path.parent)
        monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)

        df = _rth_bars("RT", d, _flat_then_step(90, 100.0, 110.0))
        store = MagicMock()
        store.to_df.return_value = df
        provider = MagicMock()
        provider.get_range.return_value = store

        backfill_outcomes(target_dates=[d], provider=provider)
        rec = json.loads(path.read_text(encoding="utf-8"))[0]
        assert rec["outcome_anchor"] == "fired_at"
        # Anchored at 11:00 the whole day is flat at 110 -> 0 %, NOT +10 %.
        assert rec["pnl_eod_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_partial_resolution_is_counted_separately(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        import open_prep.outcome_backfill as mod

        d = date(2026, 4, 17)
        path = _write_outcomes(tmp_path, d, [
            {"symbol": "HALTED", "date": d.isoformat(), "profitable_30m": None,
             "pnl_30m_pct": None, "direction": "long",
             "fired_at": "2026-04-17T11:00:00-04:00"},
        ])
        monkeypatch.setattr(mod, "OUTCOMES_DIR", path.parent)
        monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)

        df = _halted_bars("HALTED", d)
        store = MagicMock()
        store.to_df.return_value = df
        provider = MagicMock()
        provider.get_range.return_value = store

        summary = backfill_outcomes(target_dates=[d], provider=provider)
        assert summary["resolved"] == 0
        assert summary["partial"] == 1
        assert summary["failed"] == 0

        rec = json.loads(path.read_text(encoding="utf-8"))[0]
        assert rec["profitable_30m"] is None   # honest: no 30m window exists
        assert rec["pnl_eod_pct"] is not None

    def test_backfill_horizons_opt_in_refills_legacy_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default: an already-30m-resolved record is left alone (no re-fetch)."""
        import json

        import open_prep.outcome_backfill as mod

        d = date(2026, 4, 17)
        legacy = {"symbol": "OLD", "date": d.isoformat(), "profitable_30m": True,
                  "pnl_30m_pct": 1.0, "direction": "long"}
        path = _write_outcomes(tmp_path, d, [dict(legacy)])
        monkeypatch.setattr(mod, "OUTCOMES_DIR", path.parent)
        monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)

        df = _rth_bars("OLD", d, lambda i: 100.0 + i * 0.01)
        store = MagicMock()
        store.to_df.return_value = df
        provider = MagicMock()
        provider.get_range.return_value = store

        summary = backfill_outcomes(target_dates=[d], provider=provider)
        assert summary["skipped"] == 1
        assert provider.get_range.call_count == 0
        assert json.loads(path.read_text(encoding="utf-8"))[0] == legacy

        # Opt-in: the record is re-measured so the new horizons exist.
        summary = backfill_outcomes(
            target_dates=[d], provider=provider, backfill_horizons=True,
        )
        assert summary["resolved"] == 1
        rec = json.loads(path.read_text(encoding="utf-8"))[0]
        assert rec["pnl_eod_pct"] is not None
        assert rec["profitable_30m"] is not None


# ── CLI ─────────────────────────────────────────────────────────────────────


class TestHorizonCli:
    def test_defaults_request_every_horizon(self) -> None:
        args = build_parser().parse_args([])
        assert args.horizons == list(HORIZON_KEYS)
        assert args.backfill_horizons is False

    def test_explicit_subset(self) -> None:
        args = build_parser().parse_args(["--horizons", "30m,eod"])
        assert args.horizons == ["30m", "eod"]

    def test_unknown_horizon_is_rejected(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--horizons", "45m"])

    def test_primary_horizon_cannot_be_dropped(self) -> None:
        """Dropping 30m would silently change what `profitable_30m` means."""
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--horizons", "60m"])


# ── compute_hit_rates horizon switch ────────────────────────────────────────


@pytest.fixture()
def outcomes_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import open_prep.outcomes as mod

    d = tmp_path / "outcomes"
    d.mkdir()
    monkeypatch.setattr(mod, "OUTCOMES_DIR", d)
    monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)
    return d


def _store(outcomes_dir: Path, records: list[dict[str, Any]]) -> None:
    import json

    (outcomes_dir / "outcomes_2026-04-20.json").write_text(
        json.dumps(records), encoding="utf-8",
    )


class TestComputeHitRatesHorizon:
    def _records(self) -> list[dict[str, Any]]:
        base = {
            "date": "2026-04-20", "gap_pct": 2.0, "rvol": 1.5,
            "gap_bucket_label": "medium", "rvol_bucket_label": "normal",
        }
        return [
            # 30m winner, 60m loser -> the two horizons must disagree.
            {**base, "symbol": "A",
             "profitable_30m": True, "pnl_30m_pct": 1.0,
             "profitable_60m": False, "pnl_60m_pct": -2.0},
            {**base, "symbol": "B",
             "profitable_30m": True, "pnl_30m_pct": 3.0,
             "profitable_60m": False, "pnl_60m_pct": -4.0},
        ]

    def test_default_horizon_is_unchanged(self, outcomes_dir: Path) -> None:
        _store(outcomes_dir, self._records())
        rates = compute_hit_rates(lookback_days=5)
        stats = next(iter(rates.values()))
        assert stats["hit_rate"] == 1.0
        assert stats["avg_pnl_pct"] == pytest.approx(2.0)

    def test_selected_horizon_uses_its_own_fields(self, outcomes_dir: Path) -> None:
        _store(outcomes_dir, self._records())
        rates = compute_hit_rates(lookback_days=5, horizon="60m")
        stats = next(iter(rates.values()))
        assert stats["total"] == 2
        assert stats["hit_rate"] == 0.0
        assert stats["avg_pnl_pct"] == pytest.approx(-3.0)

    def test_missing_horizon_counts_as_unresolved_not_zero(
        self, outcomes_dir: Path,
    ) -> None:
        """Legacy records carry no EOD fields — they must NOT dilute the rate."""
        _store(outcomes_dir, self._records())
        rates = compute_hit_rates(lookback_days=5, horizon="eod")
        stats = next(iter(rates.values()))
        assert stats["total"] == 0
        assert stats["unresolved"] == 2
        assert stats["hit_rate"] == 0.0

    def test_lookup_reports_no_data_when_the_bucket_never_resolved(
        self, outcomes_dir: Path,
    ) -> None:
        """total==0 must reach a consumer as None, never as a 0 % hit rate.

        compute_hit_rates creates the bucket as soon as one record lands in it,
        so an all-unresolved bucket carries total=0 with hit_rate=0.0 and
        avg_pnl_pct=0.0 (pinned by the test above). Handing those to a caller
        publishes a confident "0 % historical hit rate / 0 % avg PnL" for a
        window that was never measured -- indistinguishable from a genuinely
        losing bucket. Measured on the real store 2026-07-23: at 60m the four
        tiny:* buckets read total=0 while the same buckets are 1.000 (n=3) and
        0.714 (n=7) at 30m.

        The unresolved count is still reported, because "seen 13 times, none
        measurable" is what tells an operator to run
        `outcome_backfill --backfill-horizons`, whereas an absent bucket means
        no such candidate ever appeared.
        """
        _store(outcomes_dir, self._records())
        rates = compute_hit_rates(lookback_days=5, horizon="eod")
        bucket_key, stats = next(iter(rates.items()))
        assert stats["total"] == 0 and stats["hit_rate"] == 0.0, "fixture drifted"

        gap_label, rvol_label = bucket_key.split(":", 1)
        record = self._records()[0]
        looked_up = get_symbol_hit_rate("A", record["gap_pct"], record["rvol"], rates)
        assert (looked_up["gap_bucket"], looked_up["rvol_bucket"]) == (gap_label, rvol_label)
        assert looked_up["historical_hit_rate"] is None
        assert looked_up["historical_avg_pnl_pct"] is None
        assert looked_up["historical_sample_size"] == 0
        assert looked_up["historical_unresolved"] == stats["unresolved"]

        # A bucket WITH resolved records must still come through untouched.
        resolved = get_symbol_hit_rate(
            "A", record["gap_pct"], record["rvol"],
            compute_hit_rates(lookback_days=5, horizon=DEFAULT_HORIZON),
        )
        assert resolved["historical_hit_rate"] == 1.0
        assert resolved["historical_sample_size"] == 2

    def test_directional_pair_fallback_per_horizon(self, outcomes_dir: Path) -> None:
        _store(outcomes_dir, [{
            "date": "2026-04-20", "symbol": "S", "gap_pct": 2.0, "rvol": 1.5,
            "profitable_60m": False, "pnl_60m_pct": -2.0,
            "profitable_60m_directional": True, "pnl_60m_pct_signed": 2.0,
        }])
        stats = next(iter(compute_hit_rates(lookback_days=5, horizon="60m").values()))
        assert stats["hit_rate"] == 1.0
        assert stats["avg_pnl_pct"] == pytest.approx(2.0)

    def test_unknown_horizon_raises(self, outcomes_dir: Path) -> None:
        _store(outcomes_dir, self._records())
        with pytest.raises(ValueError):
            compute_hit_rates(lookback_days=5, horizon="45m")


# ── Late-entry window completeness (F1 regression) ───────────────────────────


def test_late_entry_truncates_the_30m_window_below_its_floor() -> None:
    """A within-delay late open must not carry a sub-floor 30m window.

    First print at 09:35 (entry lag 5 min = ``_MAX_ENTRY_DELAY_MIN``): the
    last bar before 10:00 is 09:59, so the entry->exit window is 24 bar-min,
    below the 30m floor of 25. Before the fix the completeness guard measured
    from the 09:30 anchor (09:59 >= 09:55) and published a truncated window
    as ``pnl_30m_pct``. 60m/120m keep enough buffer to stay resolved.
    """
    d = date(2026, 4, 17)
    df = _rth_bars("LATEOPEN", d, lambda i: 100.0 + i * 0.10, start=dt_time(9, 35))
    res = compute_pnl_from_bars(df, "LATEOPEN", d)
    assert res is not None
    assert res["pnl_30m_pct"] is None
    assert res["profitable_30m"] is None
    assert res["pnl_60m_pct"] is not None
    assert res["pnl_120m_pct"] is not None


def test_punctual_entry_still_keeps_its_30m_window() -> None:
    """The floor must not over-reject: a 09:30 entry resolves 30m as before."""
    d = date(2026, 4, 17)
    df = _rth_bars("ONTIME", d, lambda i: 100.0 + i * 0.10)
    res = compute_pnl_from_bars(df, "ONTIME", d)
    assert res is not None
    assert res["pnl_30m_pct"] is not None
