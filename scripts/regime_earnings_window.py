"""C13/T7.3 — Earnings-window regime bucket tagging.

Companion to :mod:`scripts.regime_transition`. Where T7.2 (the
pre-trade :class:`smc_integration.earnings_filter.EarningsFilter`)
hard-blocks new entries inside the ``±pre/+post`` earnings guard,
T7.3 sits **after** the trade fact and **re-tags** ``regime_at_entry``
to ``"EARNINGS_WINDOW"`` for trades whose ``trade_date`` falls inside
a (typically wider) earnings-adjacency window.

The goal mirrors :mod:`scripts.regime_transition`: a strategy that
looks fine in the aggregate but bleeds money around earnings prints
will surface as a poor ``EARNINGS_WINDOW`` Sharpe in the C5 regime
stratifier, even though it never triggered the hard pre-trade block
(e.g. trade entered the day before the guard, exited the day after).

Out of scope (separate PRs):

* CLI wrapper — for now this module is library-only, called from the
  C5 stratification pipeline.
* Per-event-type buckets (e.g. ``"EARNINGS_PRE"`` vs
  ``"EARNINGS_POST"``) — Phase A keeps a single label for analytic
  simplicity.
* Mutating the WSH JSONL fetcher — this module only reads.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

EARNINGS_WINDOW_LABEL = "EARNINGS_WINDOW"

# Mirrors :data:`smc_integration.earnings_filter.EARNINGS_EVENT_TYPES`.
# Kept as a module-local constant so this script does not import the
# smc_integration package (T7.3 is intentionally stdlib-only).
_EARNINGS_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "Earnings",
        "EarningsAnnouncement",
        "EarningsDated",
        "EarningsRevised",
    }
)

# Phase-A defaults: a wider window than the T7.2 hard block (±1 day),
# so trades that *just* squeezed past the pre-trade filter still get
# their post-mortem stratified out.
DEFAULT_PRE_WINDOW_DAYS = 2
DEFAULT_POST_WINDOW_DAYS = 2

Trade = Mapping[str, Any]


def _to_date(value: str | _dt.date | _dt.datetime) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value).strip())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "regime_earnings_window: skipping malformed line %d in %s: %s",
                    line_no,
                    path,
                    exc,
                )
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _index_events_by_symbol(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, list[_dt.date]]:
    """Build ``{SYMBOL_UPPER: [event_date, ...]}`` for earnings rows only."""
    idx: dict[str, list[_dt.date]] = {}
    for ev in events:
        ev_type = str(ev.get("event_type", "")).strip()
        if ev_type not in _EARNINGS_EVENT_TYPES:
            continue
        sym = str(ev.get("symbol", "")).strip().upper()
        if not sym:
            continue
        try:
            ev_date = _to_date(str(ev.get("event_date", "")))
        except ValueError:
            continue
        idx.setdefault(sym, []).append(ev_date)
    for dates in idx.values():
        dates.sort()
    return idx


def load_earnings_events(
    events_jsonl: Path | str,
) -> dict[str, list[_dt.date]]:
    """Load + index earnings events from a WSH JSONL artefact.

    Returns ``{}`` if the file is missing or unreadable — same
    fail-open contract as :class:`EarningsFilter`.
    """
    path = Path(events_jsonl)
    if not path.exists():
        return {}
    try:
        events = _read_jsonl(path)
    except (OSError, UnicodeDecodeError) as exc:
        LOGGER.warning(
            "regime_earnings_window: cannot read %s (%s); treating as empty",
            path,
            exc,
        )
        return {}
    return _index_events_by_symbol(events)


def is_in_earnings_window(
    *,
    symbol: str,
    trade_date: str | _dt.date | _dt.datetime,
    events_index: Mapping[str, Sequence[_dt.date]],
    pre_window_days: int = DEFAULT_PRE_WINDOW_DAYS,
    post_window_days: int = DEFAULT_POST_WINDOW_DAYS,
) -> bool:
    """Return True iff ``trade_date`` falls within the earnings window
    for ``symbol``."""
    if pre_window_days < 0 or post_window_days < 0:
        raise ValueError("window days must be non-negative")
    sym = str(symbol).strip().upper()
    dates = events_index.get(sym)
    if not dates:
        return False
    td = _to_date(trade_date)
    lower = td - _dt.timedelta(days=pre_window_days)
    upper = td + _dt.timedelta(days=post_window_days)
    return any(lower <= ev_date <= upper for ev_date in dates)


def assign_earnings_window_bucket(
    trades: Sequence[Trade],
    *,
    events_index: Mapping[str, Sequence[_dt.date]] | None = None,
    events_jsonl: Path | str | None = None,
    symbol_col: str = "symbol",
    trade_date_col: str = "trade_date",
    regime_col: str = "regime_at_entry",
    pre_window_days: int = DEFAULT_PRE_WINDOW_DAYS,
    post_window_days: int = DEFAULT_POST_WINDOW_DAYS,
    earnings_label: str = EARNINGS_WINDOW_LABEL,
) -> list[dict[str, Any]]:
    """Re-tag ``regime_at_entry`` to ``earnings_label`` for trades whose
    ``trade_date`` is within the earnings window for ``symbol``.

    Mirrors the API of
    :func:`scripts.regime_transition.assign_transition_bucket`:

    * Input is **not mutated** — a new list of dicts is returned.
    * Re-tagged trades preserve the prior label under
      ``regime_original`` (fixed audit key, regardless of the
      caller-supplied ``regime_col``).
    * Trades missing ``symbol`` / ``trade_date`` (or with an
      unparseable ``trade_date``) pass through untouched.

    Parameters
    ----------
    trades:
        Sequence of trade mappings.
    events_index:
        Pre-built index returned by :func:`load_earnings_events` (or
        constructed by the caller). Mutually exclusive with
        ``events_jsonl``; if both are passed, ``events_index`` wins.
    events_jsonl:
        Path to a WSH JSONL file. Loaded lazily if ``events_index`` is
        not supplied. Missing or unreadable files fail open (no
        re-tagging) — Phase A must not corrupt analytics on data gaps.
    pre_window_days, post_window_days:
        Calendar-day window around the earnings event date.
    earnings_label:
        Label written into ``regime_col`` for in-window trades.

    Returns
    -------
    A new list of dicts, same length and order as ``trades``.
    """
    if pre_window_days < 0 or post_window_days < 0:
        raise ValueError("window days must be non-negative")
    if not trades:
        return []

    if events_index is None:
        if events_jsonl is None:
            # No data source — no re-tagging. Return shallow copies so
            # callers can't accidentally mutate the input via the
            # returned list.
            return [dict(t) for t in trades]
        events_index = load_earnings_events(events_jsonl)

    if not events_index:
        return [dict(t) for t in trades]

    out: list[dict[str, Any]] = []
    for trade in trades:
        new = dict(trade)
        symbol = trade.get(symbol_col)
        trade_date = trade.get(trade_date_col)
        if symbol in (None, "") or trade_date in (None, ""):
            out.append(new)
            continue
        try:
            in_window = is_in_earnings_window(
                symbol=str(symbol),
                trade_date=trade_date,
                events_index=events_index,
                pre_window_days=pre_window_days,
                post_window_days=post_window_days,
            )
        except ValueError:
            # Unparseable trade_date — leave the trade untouched
            # rather than crash the whole batch.
            out.append(new)
            continue
        if in_window:
            new["regime_original"] = trade.get(regime_col)
            new[regime_col] = earnings_label
        out.append(new)
    return out


def earnings_window_share(
    original_trades: Sequence[Trade],
    rewritten_trades: Sequence[Mapping[str, Any]],
    *,
    earnings_label: str = EARNINGS_WINDOW_LABEL,
    regime_col: str = "regime_at_entry",
) -> float:
    """Fraction of trades that ended up in the earnings-window bucket.

    Returns 0.0 when ``rewritten_trades`` is empty.
    """
    total = len(rewritten_trades)
    if total == 0:
        return 0.0
    hits = sum(1 for t in rewritten_trades if t.get(regime_col) == earnings_label)
    return hits / total


__all__ = [
    "DEFAULT_POST_WINDOW_DAYS",
    "DEFAULT_PRE_WINDOW_DAYS",
    "EARNINGS_WINDOW_LABEL",
    "assign_earnings_window_bucket",
    "earnings_window_share",
    "is_in_earnings_window",
    "load_earnings_events",
]
