"""``squeeze_on`` is not merely "sometimes null" at 4H — it can never be anything else.

``compute_squeeze_on`` fails closed below ``period + _SQUEEZE_MIN_WARMUP_BARS``
aggregated bars, because the Keltner half is recursive and a mis-warmed boolean
would be a wrong verdict rather than no verdict. The bar cache bounds a symbol
at ``cache._MAX_EXPANDED_BAR_CAP`` retained 1-minute bars, and the RTH-anchored
4H view buckets a 09:30-16:00 session into two candles — so the cap converts to
far fewer 4H candles than the warm-up needs. ``compute.py`` states this in a
comment next to ``_TF_RAW_BAR_REQUIREMENTS``; the wire contract in
``services/live_overlay_daemon/README.md`` described it only as "the history is
too short", which reads as a transient condition a consumer can wait out.

These tests measure the reachability instead of restating it, and pin the README
to the measurement: raise the cap or lower the warm-up and the 4H claim in the
docs goes red in the same run as the arithmetic that made it true.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from services.live_overlay_daemon import cache, compute

README = Path(__file__).resolve().parents[1] / "services" / "live_overlay_daemon" / "README.md"


def _densest_possible_history() -> list[dict[str, object]]:
    """Exactly ``_MAX_EXPANDED_BAR_CAP`` 1m bars, all inside US regular sessions.

    Extended-session minutes are retained too but bucket to ``None`` at 1H/4H,
    so spending the whole budget inside RTH is the best case a symbol can ever
    reach — an upper bound, not a typical one.
    """
    bars: list[dict[str, object]] = []
    day = datetime.datetime(2026, 1, 5, 14, 30, tzinfo=datetime.UTC)  # 09:30 ET, a Monday
    while len(bars) < cache._MAX_EXPANDED_BAR_CAP:
        if day.weekday() < 5:
            for minute in range(390):  # 09:30-16:00 ET
                if len(bars) >= cache._MAX_EXPANDED_BAR_CAP:
                    break
                stamp = day + datetime.timedelta(minutes=minute)
                price = 100.0 + (len(bars) % 7) * 0.1
                bars.append(
                    {
                        "ts_event": int(stamp.timestamp()) * 1_000_000_000,
                        "open": price,
                        "high": price + 0.5,
                        "low": price - 0.5,
                        "close": price + 0.1,
                        "volume": 1000,
                    }
                )
        day += datetime.timedelta(days=1)
    return bars


def test_a_4h_squeeze_verdict_is_unreachable_at_the_cache_cap() -> None:
    """The best case the cache can hold still falls short of the warm-up."""
    bars = _densest_possible_history()
    needed = 20 + compute._SQUEEZE_MIN_WARMUP_BARS
    aggregated = compute._bars_for_timeframe(bars, "4H")

    assert len(aggregated) < needed, (
        f"4H now reaches {len(aggregated)} candles against a warm-up of {needed} — "
        "a 4H squeeze verdict has become reachable, so the README row for "
        "`squeeze_on` must stop calling it always-null"
    )
    assert compute.compute_squeeze_on(aggregated, period=20) is None


def test_1h_stays_reachable_so_the_gate_is_not_simply_off() -> None:
    """Counter-test: the fail-closed branch must not be swallowing every timeframe."""
    aggregated = compute._bars_for_timeframe(_densest_possible_history(), "1H")
    assert len(aggregated) >= 20 + compute._SQUEEZE_MIN_WARMUP_BARS
    assert compute.compute_squeeze_on(aggregated, period=20) is not None, (
        "1H lost its squeeze verdict too — the warm-up threshold or the RTH "
        "bucketing changed and the field is now dark on every hourly view"
    )


def test_the_wire_contract_states_the_4h_verdict_is_structural() -> None:
    """A consumer reads the README, not `_TF_RAW_BAR_REQUIREMENTS`."""
    row = next(
        line for line in README.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `squeeze_on` |")
    )
    assert "always null at `4H`" in row, (
        "the `squeeze_on` row no longer tells a consumer that 4H is structurally "
        f"null rather than temporarily unwarmed: {row}"
    )
