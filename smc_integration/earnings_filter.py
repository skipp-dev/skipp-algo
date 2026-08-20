"""C13/T7.2 — Pre-trade earnings filter.

Reads the daily WSH events JSONL produced by
:mod:`scripts.wsh_earnings_calendar` and decides whether a candidate
intent for ``symbol`` on ``trade_date`` should be **blocked** because
an earnings event falls inside the configured guard-window.

The filter is deliberately conservative:

* If the JSONL is missing or unreadable, the filter returns
  ``EarningsFilterDecision(blocked=False, reason="WSH_DATA_MISSING")``
  — Phase A must not block trades on data unavailability.
* If the JSONL is present but holds no events for the symbol, the
  filter returns ``blocked=False`` with reason ``NO_EARNINGS_EVENT``.
* If at least one earnings event for ``symbol`` falls inside
  ``[trade_date - pre_window_days, trade_date + post_window_days]``,
  the filter returns ``blocked=True`` with the offending event date.

Default windows mirror the C13 sprint plan: block trades within 1
**calendar** day before and 1 **calendar** day after a confirmed
earnings release. (We deliberately use calendar days — not business
days — because pre-market / weekend earnings releases still affect
the next session, and a calendar window keeps the rule trivial to
audit.) Configure via constructor args.

The output ``EarningsFilterDecision`` is serialisable for audit-log
records — see :func:`as_audit_dict`.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# Whitelist of WSH event-types that count as "earnings". Mirrors
# scripts.wsh_earnings_calendar.WSH_EARNINGS_EVENT_TYPES so changing
# either side requires an explicit edit here.
EARNINGS_EVENT_TYPES: frozenset[str] = frozenset({
    "Earnings",
    "EarningsAnnouncement",
    "EarningsDated",
    "EarningsRevised",
})

# Conservative default guard windows (calendar days).
DEFAULT_PRE_WINDOW_DAYS = 1
DEFAULT_POST_WINDOW_DAYS = 1

# What to do when the calendar cannot be consulted at all.
#
# ``block`` is the default since 2026-08-19 (operator decision): "I do not
# know whether this symbol reports today" must not be a reason to trade. The
# previous fail-open behaviour was invisible in practice — see
# ``data_available`` — so the gate reported success while never gating.
# ``pass`` stays available for replays and backfills of periods that were
# genuinely unfiltered, where blocking would rewrite history.
MISSING_DATA_POLICIES: frozenset[str] = frozenset({"block", "pass"})
DEFAULT_MISSING_DATA_POLICY = "block"


@dataclass(frozen=True)
class EarningsFilterDecision:
    """Verdict for a single (symbol, trade_date) pair."""

    symbol: str
    trade_date: str  # ISO YYYY-MM-DD
    blocked: bool
    reason: str
    matched_event_date: str | None = None
    matched_event_type: str | None = None
    pre_window_days: int = DEFAULT_PRE_WINDOW_DAYS
    post_window_days: int = DEFAULT_POST_WINDOW_DAYS

    def as_audit_dict(self) -> dict[str, Any]:
        """Audit-log entry serialisation (sort-keys downstream)."""
        return {
            "kind": "earnings_filter_decision",
            **asdict(self),
        }


@dataclass(frozen=True)
class EarningsFilterStats:
    """Counts produced when filter is applied across many candidates."""

    candidates: int = 0
    blocked: int = 0
    passed: int = 0
    missing_data: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
                    "earnings_filter: skipping malformed line %d in %s: %s",
                    line_no,
                    path,
                    exc,
                )
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


class EarningsFilter:
    """Pre-trade earnings filter, fed by a daily WSH JSONL artefact."""

    def __init__(
        self,
        events_jsonl: Path | str | None,
        *,
        pre_window_days: int = DEFAULT_PRE_WINDOW_DAYS,
        post_window_days: int = DEFAULT_POST_WINDOW_DAYS,
        on_missing_data: str = DEFAULT_MISSING_DATA_POLICY,
    ) -> None:
        if pre_window_days < 0 or post_window_days < 0:
            raise ValueError("guard-window days must be non-negative")
        if on_missing_data not in MISSING_DATA_POLICIES:
            raise ValueError(
                f"on_missing_data must be one of {sorted(MISSING_DATA_POLICIES)}, "
                f"got {on_missing_data!r}"
            )
        self._pre = int(pre_window_days)
        self._post = int(post_window_days)
        self._on_missing_data = on_missing_data
        self._events_path: Path | None = (
            Path(events_jsonl) if events_jsonl is not None else None
        )
        # Lazy-load on first decide() so unit tests can patch the file
        # contents post-construction.
        self._index: dict[str, list[dict[str, Any]]] | None = None
        self._data_available: bool = True
        if self._events_path is None or not self._events_path.exists():
            self._data_available = False
            self._index = {}

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def data_available(self) -> bool:
        """Whether a WSH JSONL with at least one indexable event was read.

        A PRESENT but empty file counts as MISSING (2026-08-19). Until then
        only ``exists()`` was checked, so the 22 zero-byte snapshots the WSH
        feed had been writing since 2026-06-11 were accepted as valid data and
        every symbol got the positive verdict ``NO_EARNINGS_EVENT`` — a claim
        that the calendar had been consulted. ``WSH_DATA_MISSING``, the state
        built for exactly this situation, could never fire.
        """
        if self._index is None:
            self._lookup("")
        return self._data_available

    @property
    def on_missing_data(self) -> str:
        """Policy applied when the calendar is unavailable ('block'|'pass')."""
        return self._on_missing_data

    def reload(self) -> None:
        """Force re-read of the JSONL (e.g. after file rotation)."""
        self._index = None
        if self._events_path is None or not self._events_path.exists():
            self._index = {}
            self._data_available = False
        else:
            # Emptiness is only knowable after reading; ``_build_index``
            # re-decides ``_data_available`` on the next lookup.
            self._data_available = True

    def decide(
        self,
        *,
        symbol: str,
        trade_date: str | _dt.date,
    ) -> EarningsFilterDecision:
        """Return the block/pass verdict for one candidate trade."""
        symbol_norm = str(symbol).strip().upper()
        try:
            td = _to_date(trade_date)
        except ValueError as exc:
            raise ValueError(f"trade_date not ISO-8601: {trade_date!r}") from exc

        if not self._data_available:
            return EarningsFilterDecision(
                symbol=symbol_norm,
                trade_date=td.isoformat(),
                blocked=self._on_missing_data == "block",
                reason="WSH_DATA_MISSING",
                pre_window_days=self._pre,
                post_window_days=self._post,
            )

        events = self._lookup(symbol_norm)
        # ``_lookup`` may flip ``_data_available`` to False if the JSONL
        # became unreadable between construction and now (caught inside
        # ``_build_index``). Re-check so we surface ``WSH_DATA_MISSING``
        # rather than a misleading ``NO_EARNINGS_EVENT`` pass.
        if not self._data_available:
            return EarningsFilterDecision(
                symbol=symbol_norm,
                trade_date=td.isoformat(),
                blocked=self._on_missing_data == "block",
                reason="WSH_DATA_MISSING",
                pre_window_days=self._pre,
                post_window_days=self._post,
            )
        if not events:
            return EarningsFilterDecision(
                symbol=symbol_norm,
                trade_date=td.isoformat(),
                blocked=False,
                reason="NO_EARNINGS_EVENT",
                pre_window_days=self._pre,
                post_window_days=self._post,
            )

        lower = td - _dt.timedelta(days=self._pre)
        upper = td + _dt.timedelta(days=self._post)
        for ev in events:
            ev_type = str(ev.get("event_type", "")).strip()
            if ev_type not in EARNINGS_EVENT_TYPES:
                continue
            try:
                ev_date = _to_date(str(ev.get("event_date", "")))
            except ValueError:
                continue
            if lower <= ev_date <= upper:
                return EarningsFilterDecision(
                    symbol=symbol_norm,
                    trade_date=td.isoformat(),
                    blocked=True,
                    reason="EARNINGS_WINDOW",
                    matched_event_date=ev_date.isoformat(),
                    matched_event_type=ev_type,
                    pre_window_days=self._pre,
                    post_window_days=self._post,
                )

        return EarningsFilterDecision(
            symbol=symbol_norm,
            trade_date=td.isoformat(),
            blocked=False,
            reason="OUTSIDE_GUARD_WINDOW",
            pre_window_days=self._pre,
            post_window_days=self._post,
        )

    def filter_candidates(
        self,
        candidates: Iterable[tuple[str, str | _dt.date]],
    ) -> tuple[list[EarningsFilterDecision], EarningsFilterStats]:
        """Apply the filter across many (symbol, trade_date) tuples."""
        decisions: list[EarningsFilterDecision] = []
        blocked = 0
        passed = 0
        missing = 0
        total = 0
        for symbol, trade_date in candidates:
            total += 1
            decision = self.decide(symbol=symbol, trade_date=trade_date)
            decisions.append(decision)
            # ``missing`` is orthogonal to blocked/passed: under the
            # fail-closed default a missing calendar BLOCKS, so counting it as
            # passed (the pre-2026-08-19 accounting) would have understated
            # ``blocked`` and overstated ``passed`` in every audit summary.
            if decision.reason == "WSH_DATA_MISSING":
                missing += 1
            if decision.blocked:
                blocked += 1
            else:
                passed += 1
        stats = EarningsFilterStats(
            candidates=total,
            blocked=blocked,
            passed=passed,
            missing_data=missing,
        )
        return decisions, stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lookup(self, symbol_norm: str) -> list[dict[str, Any]]:
        if self._index is None:
            self._index = self._build_index()
        return self._index.get(symbol_norm, [])

    def _build_index(self) -> dict[str, list[dict[str, Any]]]:
        idx: dict[str, list[dict[str, Any]]] = {}
        if self._events_path is None or not self._events_path.exists():
            # Honour the docstring contract: missing JSONL must downgrade
            # to ``WSH_DATA_MISSING`` (Phase A must not silently treat
            # "no file" as "no earnings event").
            self._data_available = False
            return idx
        try:
            events = _read_jsonl(self._events_path)
        except (OSError, UnicodeDecodeError) as exc:
            # Honour the docstring contract: unreadable JSONL must
            # downgrade to ``WSH_DATA_MISSING`` (Phase A must not block
            # trades on data unavailability).
            LOGGER.warning(
                "earnings_filter: cannot read %s (%s); treating as missing",
                self._events_path,
                exc,
            )
            self._data_available = False
            return idx
        for ev in events:
            sym = str(ev.get("symbol", "")).strip().upper()
            if not sym:
                continue
            idx.setdefault(sym, []).append(ev)
        if not idx:
            # A readable file that yields NO indexable event is data we do not
            # have, not a market-wide absence of earnings. The WSH feed writes
            # a zero-byte snapshot on its rc=2 path ("feed returned ZERO
            # events"), and every such day was silently answered with the
            # positive verdict NO_EARNINGS_EVENT until 2026-08-19. Measured
            # then: 22 snapshots on disk, all 0 bytes, 41/41 feed markers
            # degraded since 2026-06-11.
            LOGGER.warning(
                "earnings_filter: %s yielded no indexable events; treating as "
                "missing data (policy=%s)",
                self._events_path,
                self._on_missing_data,
            )
            self._data_available = False
        return idx
