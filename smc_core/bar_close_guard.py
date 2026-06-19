"""Bar-close guard helper (H-7, system review 2026-04-24).

Background
----------
Multiple SMC derivation paths consume an OHLC DataFrame and snapshot
"the most recent bar" via ``df.iloc[-1]`` (vol-regime ATR, structure
state, imbalance lifecycle, HTF bias, etc.). When the live provider
appends a *partially formed* bar (an in-progress 5m candle, an
unfinished daily session), every one of these consumers reads that
partial bar as the closed reference — silently producing decisions on
a moving close.

There is no upstream ``is_closed`` flag on the bars (databento
``get_range`` returns OHLC frames with no partial-bar marker). The
only deterministic signal we have is the bar's start timestamp plus
the interval: a bar starting at ``t`` with interval ``Δ`` is
**closed** at exterior wall-clock time ``t + Δ`` and not before.

Contract
--------
:func:`guard_closed_bars` accepts a DataFrame whose ``timestamp``
column is epoch seconds (the project-wide convention enforced by
``coerce_timestamps_to_epoch_seconds``) and returns a copy with any
trailing rows whose close-time exceeds ``now`` removed. Rows in the
middle of the frame are never dropped; only the contiguous in-progress
suffix.

Callers that have no notion of "now" (purely historical replays,
fixture frames) may pass ``now=None`` to opt out — the guard is a
no-op in that case. Production paths that need bar-close semantics
must pass an explicit ``now`` (typically ``time.time()`` or the
ingestion-layer ``as_of`` epoch).

This helper is intentionally framework-free: no pandas imports at
module top-level (DataFrames are typed loosely), no logging, no
timezone normalisation. The single responsibility is "drop trailing
not-yet-closed bars".
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - type-only
    import pandas as pd


# Canonical interval → seconds map. Keep this short and explicit;
# unknown intervals raise rather than silently default to 0.
_INTERVAL_SECONDS: Final[Mapping[str, int]] = {
    "1m": 60,
    "5m": 5 * 60,
    "10m": 10 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
}


def interval_seconds(interval: str) -> int:
    """Return the bar duration in seconds for a canonical interval token.

    Raises :class:`ValueError` for unknown intervals so callers fail
    loudly rather than silently mis-classifying bars.
    """
    try:
        return _INTERVAL_SECONDS[interval]
    except KeyError as exc:
        raise ValueError(
            f"Unknown bar interval {interval!r}; "
            f"expected one of {sorted(_INTERVAL_SECONDS)}"
        ) from exc


def guard_closed_bars(
    df: pd.DataFrame,
    *,
    interval: str,
    now: float | None,
    timestamp_column: str = "timestamp",
) -> pd.DataFrame:
    """Return ``df`` with any trailing in-progress bars removed.

    Parameters
    ----------
    df:
        OHLC frame whose ``timestamp_column`` holds epoch seconds for
        the **start** of each bar.
    interval:
        Canonical interval token (``"1m"``, ``"5m"``, ``"1h"`` …).
    now:
        Reference wall-clock time in epoch seconds. ``None`` disables
        the guard (returns ``df`` unchanged) — historical replays and
        fixture frames may pass ``None``; production paths must pass
        an explicit value.
    timestamp_column:
        Column holding bar-start epoch seconds. Defaults to the
        project-wide ``"timestamp"`` convention.

    Notes
    -----
    Only the contiguous suffix of in-progress bars is dropped: a
    legitimate gap in the middle of the frame (e.g. a stale
    historical row whose close exceeds ``now`` due to clock skew) is
    preserved on purpose — it is the caller's responsibility to keep
    historical frames sorted and ``now`` monotonic.
    """
    if now is None:
        return df
    if df is None or len(df) == 0:
        return df
    if timestamp_column not in df.columns:
        # Fail-soft: the guard cannot make a decision without the
        # timestamp column, so leave the frame untouched.
        return df

    duration = interval_seconds(interval)
    threshold = float(now)

    timestamps = df[timestamp_column]
    # Walk the suffix only.
    drop_count = 0
    for value in reversed(timestamps.tolist()):
        try:
            start = float(value)
        except (TypeError, ValueError):
            break
        close_time = start + duration
        if close_time > threshold:
            drop_count += 1
        else:
            break

    if drop_count == 0:
        return df
    if drop_count >= len(df):
        return df.iloc[0:0]
    return df.iloc[: len(df) - drop_count]
