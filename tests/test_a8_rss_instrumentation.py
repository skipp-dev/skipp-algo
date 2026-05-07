"""Unit tests for A8.1 RSS instrumentation helpers.

A8.1 fix: ``_rss_mib*`` legacy helpers returned ``ru_maxrss`` (high-watermark,
not current). New ``_rss_current_mib*`` reads ``/proc/self/status:VmRSS`` for
instantaneous RSS on Linux. ``_fmt_rss_pair()`` emits both ``cur=`` and
``peak=`` in a single string preserving the ``rss=`` log-grep key prefix.

These tests verify:
1. Back-compat aliases preserve identity (no behavior change for legacy callers).
2. Current-RSS helpers return positive floats on Linux, ``None`` elsewhere.
3. ``_fmt_rss_pair()`` produces the documented ``cur=XMiB peak=YMiB`` shape.
"""

from __future__ import annotations

import sys

import pytest


# --- source-of-truth: scripts/databento_production_export.py ---------------


def test_production_export_back_compat_alias_is_peak() -> None:
    from scripts import databento_production_export as ex

    assert ex._rss_mib_snapshot is ex._rss_peak_mib_snapshot, (
        "A8.1 back-compat: _rss_mib_snapshot must remain identity-aliased to "
        "_rss_peak_mib_snapshot so legacy delta-tracking call sites in Step 8 "
        "continue to record peak-RSS deltas without behavior change."
    )


def test_production_export_peak_returns_float_on_posix() -> None:
    from scripts import databento_production_export as ex

    val = ex._rss_peak_mib_snapshot()
    if sys.platform.startswith(("linux", "darwin")):
        assert isinstance(val, float) and val > 0.0
    # Windows (no `resource` module) returns None — uncovered on CI but harmless.


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="VmRSS is Linux-only")
def test_production_export_current_returns_positive_on_linux() -> None:
    from scripts import databento_production_export as ex

    val = ex._rss_current_mib_snapshot()
    assert isinstance(val, float)
    assert val > 0.0
    # Sanity: current RSS for a Python interpreter must be at least ~5 MiB and
    # cannot exceed the peak watermark.
    peak = ex._rss_peak_mib_snapshot()
    assert peak is not None
    assert val <= peak + 1.0  # rounding tolerance


def test_production_export_fmt_rss_pair_shape() -> None:
    from scripts import databento_production_export as ex

    out = ex._fmt_rss_pair()
    # Must contain both keys for downstream grep on the new format.
    assert "cur=" in out, out
    assert "peak=" in out, out
    # Either a numeric MiB or 'n/a' on platforms without /proc.
    assert "MiB" in out or "n/a" in out, out


# --- mirror: databento_volatility_screener.py ------------------------------


def test_volatility_screener_back_compat_alias_is_peak() -> None:
    import databento_volatility_screener as vs

    assert vs._rss_mib is vs._rss_peak_mib, (
        "A8.1 back-compat: _rss_mib must remain identity-aliased to _rss_peak_mib."
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="VmRSS is Linux-only")
def test_volatility_screener_current_returns_positive_on_linux() -> None:
    import databento_volatility_screener as vs

    val = vs._rss_current_mib()
    assert isinstance(val, float)
    assert val > 0.0


def test_volatility_screener_fmt_rss_pair_shape() -> None:
    import databento_volatility_screener as vs

    out = vs._fmt_rss_pair()
    assert "cur=" in out, out
    assert "peak=" in out, out
    assert "MiB" in out or "n/a" in out, out
