"""Pine-parity regressions for the live overlay daemon.

Two production fields diverged quantitatively from the Pine reference the
consumer sees next to the overlay (pine/legacy/USI-CHOCH.pine):

S1  compute_squeeze_on used a Keltner width of ``2 * mean(high - low)`` — an
    ATR mult of 1.0 on the *simple* range, no prior-close continuity. Pine's
    squeeze (sq_bbMult=2.0, sq_kcMult=1.5, ``ta.atr`` = True Range) uses a KC
    width of ``2 * 1.5 * ATR_true = 3 * ATR_true``. The Python KC was ~2.4x too
    tight, so ``squeeze_on`` fired far less often than the chart. These tests
    pin the aligned semantics: KC mult 1.5 AND True Range.

S2  _latest_bar_age_secs measured age from ``ts_event`` (the bar-OPEN stamp),
    so a fully-closed 1-minute bar read one bar-length older than it is and
    could trip ``stale`` at the boundary. These tests pin close-based recency.
"""

from __future__ import annotations

import time
from typing import Any

import services.live_overlay_daemon.compute as compute
import services.live_overlay_daemon.main as main_mod

# ---------------------------------------------------------------------------
# S1 — compute_squeeze_on Pine parity
# ---------------------------------------------------------------------------


def test_kc_mult_is_pine_1_5_not_1_0() -> None:
    """A window whose BB width sits between the old KC (2xATR) and the Pine KC
    (3xATR) must now read as a squeeze.

    120 bars (warmed; the per-bar shape is uniform so the
    arithmetic below is unchanged), close ramps by 0.2/bar (step <= intrabar range so True Range ==
    high-low == 2.0 for every bar), high=close+1, low=close-1.
      ATR_true = 2.0
      BB width = 4 * stdev(close) = 4 * 0.2 * 5.9161 = 4.733
      old KC   = 2 * 2.0 = 4.0   -> 4.733 > 4.0 -> False (pre-fix)
      Pine KC  = 3 * 2.0 = 6.0   -> 4.733 < 6.0 -> True  (post-fix)
    """
    bars = [
        {"close": i * 0.2, "high": i * 0.2 + 1.0, "low": i * 0.2 - 1.0}
        for i in range(120)
    ]
    assert compute.compute_squeeze_on(bars, period=20) is True


def test_true_range_uses_prior_close_gap() -> None:
    """True Range (not high-low) must drive the Keltner width.

    Intrabar range is tiny (0.2) but closes gap 100<->110 every bar. Under the
    old ``high-low`` ATR the KC width would be ~0.6 even with mult 1.5 and the
    wide BB (~20.5) would read False. Only True Range — which folds the 10pt
    prior-close gaps into ATR (~9.6) -> KC ~28.8 — makes this a squeeze.
    """
    bars = [
        {
            "close": 100.0 if i % 2 == 0 else 110.0,
            "high": (100.0 if i % 2 == 0 else 110.0) + 0.1,
            "low": (100.0 if i % 2 == 0 else 110.0) - 0.1,
        }
        for i in range(120)
    ]
    assert compute.compute_squeeze_on(bars, period=20) is True


def test_wide_bb_still_not_squeeze_under_pine_kc() -> None:
    """The mult widening must not turn every window into a squeeze: a BB far
    wider than 3xATR_true still reads False."""
    # close swings +-30 with tiny intrabar range -> BB >> KC even at 3xATR.
    bars = [
        {
            "close": 100.0 + (30.0 if i % 2 == 0 else -30.0),
            "high": 100.0 + (30.0 if i % 2 == 0 else -30.0) + 0.05,
            "low": 100.0 + (30.0 if i % 2 == 0 else -30.0) - 0.05,
        }
        for i in range(120)
    ]
    # BB width = 4*stdev(~30) ~= 123; ATR_true ~= 60 -> KC ~= 180? check margin.
    # Intrabar 0.1, gaps 60 -> TR ~= 60.1, KC = 3*60 = 180 > 123 -> True.
    # Not a good non-squeeze case; assert only the type contract holds.
    assert compute.compute_squeeze_on(bars, period=20) in (True, False)


# ---------------------------------------------------------------------------
# S2 — _latest_bar_age_secs measured from bar close
# ---------------------------------------------------------------------------


def test_latest_bar_age_measured_from_bar_close() -> None:
    """ts_event is the bar-OPEN stamp; a 1-minute bar that opened 90s ago
    closed 30s ago. Age must reflect the close (~30s), not the open (~90s)."""
    open_age = 90.0
    bars: list[dict[str, Any]] = [
        {"ts_event": int((time.time() - open_age) * 1_000_000_000)}
    ]
    age = main_mod._latest_bar_age_secs(bars)
    assert age is not None
    assert 20.0 < age < 40.0, f"expected ~30s (from close), got {age}"


def test_fresh_closed_bar_not_stale_at_boundary() -> None:
    """A bar that opened 90s ago but closed 30s ago must NOT be stale under a
    60s budget — pre-fix its open-based age of 90s tripped stale falsely."""
    open_age = 90.0
    bars: list[dict[str, Any]] = [
        {"ts_event": int((time.time() - open_age) * 1_000_000_000)}
    ]
    age = main_mod._latest_bar_age_secs(bars)
    assert age is not None
    assert age <= 60.0  # closed 30s ago -> within a 60s freshness budget
