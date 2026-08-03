"""Thread-safe rolling OPRA definitions, prints, and shadow snapshots."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import databento_usage
from newsstack_fmp.opra_uoa import OpraDefinitionRecord, detect_unusual_options_activity


def _mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    method = getattr(record, "to_dict", None)
    if callable(method):
        value = method()
        if isinstance(value, Mapping):
            return dict(value)
    return {
        "instrument_id": getattr(record, "instrument_id", None),
        "ts_event": getattr(record, "ts_event", None),
        "ts_recv": getattr(record, "ts_recv", None),
        "sequence": getattr(record, "sequence", None),
        "price": getattr(record, "price", None),
        "size": getattr(record, "size", None),
        "side": getattr(record, "side", None),
        "publisher_id": getattr(record, "publisher_id", None),
        "bid_px_00": getattr(record, "bid_px_00", None),
        "ask_px_00": getattr(record, "ask_px_00", None),
        "underlying": getattr(record, "underlying", None),
        "asset": getattr(record, "asset", None),
        "strike_price": getattr(record, "strike_price", None),
        "expiration": getattr(record, "expiration", None),
        "instrument_class": getattr(record, "instrument_class", None),
        "raw_symbol": getattr(record, "raw_symbol", None),
    }


def _price(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric / 1_000_000_000.0 if abs(numeric) >= 1_000_000 else numeric


def _timestamp_ns(value: Any) -> int:
    if hasattr(value, "value"):
        value = value.value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _quote_side(price: float | None, bid: float | None, ask: float | None) -> tuple[str, str]:
    if price is None or bid is None or ask is None or ask <= bid:
        return "N", "unknown"
    if price >= ask:
        return "B", "quote_rule"
    if price <= bid:
        return "A", "quote_rule"
    return "N", "inside_spread"


class OpraShadowState:
    def __init__(self, *, hotlist: tuple[str, ...], window_seconds: int, min_premium: float) -> None:
        self.hotlist = frozenset(ticker.upper() for ticker in hotlist)
        self.window_ns = int(window_seconds) * 1_000_000_000
        self.min_premium = float(min_premium)
        self._definitions: dict[int, tuple[OpraDefinitionRecord, int]] = {}
        self._pending: dict[int, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=100))
        self._trades: deque[dict[str, Any]] = deque()
        self._seen: set[tuple[Any, ...]] = set()
        self._seen_order: deque[tuple[Any, ...]] = deque(maxlen=200_000)
        # Latest tcbbo BBO per instrument. Counting happens on the trades
        # schema (its ``sequence`` distinguishes genuine identical child
        # fills); tcbbo — which has no sequence field at all — degrades to a
        # pure quote source for aggressor classification (issue #4368).
        self._last_bbo: dict[int, tuple[float | None, float | None]] = {}
        self._lock = threading.RLock()
        self.duplicates = 0
        self.unknown_instruments = 0
        self.out_of_order = 0
        self.last_event_ns = 0
        self.started_at = datetime.now(UTC)
        self.session_date: str | None = None

    def update_hotlist(self, hotlist: tuple[str, ...]) -> None:
        """Apply an operator hotlist change and purge removed underlyings."""
        normalized = frozenset(ticker.strip().upper() for ticker in hotlist if ticker.strip())
        with self._lock:
            self.hotlist = normalized
            allowed_ids = {
                instrument_id
                for instrument_id, (definition, _ts) in self._definitions.items()
                if definition.underlying in normalized
            }
            self._definitions = {
                instrument_id: value
                for instrument_id, value in self._definitions.items()
                if instrument_id in allowed_ids
            }
            self._trades = deque(
                trade
                for trade in self._trades
                if int(trade.get("instrument_id") or 0) in allowed_ids
            )
            self._pending = defaultdict(
                lambda: deque(maxlen=100),
                {
                    instrument_id: rows
                    for instrument_id, rows in self._pending.items()
                    if instrument_id in allowed_ids
                },
            )
            self._last_bbo = {
                instrument_id: value
                for instrument_id, value in self._last_bbo.items()
                if instrument_id in allowed_ids
            }

    def _roll_session(self, ts_ns: int) -> None:
        if ts_ns <= 0:
            return
        session = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).date().isoformat()
        if self.session_date is None:
            self.session_date = session
            return
        if session == self.session_date:
            return
        self.session_date = session
        self._definitions.clear()
        self._pending.clear()
        self._trades.clear()
        self._seen.clear()
        self._seen_order.clear()
        self._last_bbo.clear()
        self.last_event_ns = 0

    def add_definition(self, value: OpraDefinitionRecord | Mapping[str, Any], *, ts_ns: int = 0) -> int:
        try:
            if isinstance(value, OpraDefinitionRecord):
                record = value
            else:
                row = dict(value)
                if row.get("strike_price") is not None:
                    row["strike_price"] = _price(row["strike_price"])
                record = OpraDefinitionRecord.from_row(row)
        except (KeyError, TypeError, ValueError):
            databento_usage.record(
                dataset="OPRA.PILLAR",
                schema="definition",
                mode="live",
                consumer="opra-shadow",
                dropped_records=1,
            )
            return 0
        if self.hotlist and record.underlying not in self.hotlist:
            return 0
        with self._lock:
            if not ts_ns:
                pending = self._pending.get(record.instrument_id)
                pending_value = pending[0].get("ts_event") if pending else None
                ts_ns = _timestamp_ns(pending_value)
            if not ts_ns:
                ts_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
            self._roll_session(ts_ns)
            self._definitions[record.instrument_id] = (record, int(ts_ns))
            pending = list(self._pending.pop(record.instrument_id, ()))
        accepted = 0
        for trade in pending:
            accepted += int(self.add_trade(trade, count_unknown=False))
        return accepted

    def update_quote(self, value: Mapping[str, Any] | Any) -> None:
        """Record the latest tcbbo BBO for an instrument — quotes are never counted.

        The BBO feeds ``_quote_side`` when the instrument's next trades-schema
        record arrives. Within a burst of identical child fills the BBO is
        constant, so classification quality matches the old at-trade BBO; the
        only skew is a trade processed before its tcbbo twin, which then uses
        the previous trade's BBO (or fails open to "unknown" on first sight).
        """
        row = _mapping(value)
        try:
            instrument_id = int(row.get("instrument_id") or 0)
        except (TypeError, ValueError):
            return
        if not instrument_id:
            return
        bid = _price(row.get("bid_px_00"))
        ask = _price(row.get("ask_px_00"))
        with self._lock:
            self._last_bbo[instrument_id] = (bid, ask)

    def add_trade(self, value: Mapping[str, Any] | Any, *, count_unknown: bool = True) -> bool:
        row = _mapping(value)
        try:
            instrument_id = int(row.get("instrument_id") or 0)
        except (TypeError, ValueError):
            return False
        event_value = row.get("ts_event")
        event_source = "ts_event"
        if event_value is None:
            event_value = row.get("ts_recv")
            event_source = "ts_recv"
        ts_event = _timestamp_ns(event_value)
        key = (
            instrument_id,
            ts_event,
            row.get("sequence"),
            row.get("price"),
            row.get("size"),
        )
        with self._lock:
            self._roll_session(ts_event)
            if key in self._seen:
                self.duplicates += 1
                return False
            definition = self._definitions.get(instrument_id)
            if definition is None:
                self._pending[instrument_id].append(row)
                if count_unknown:
                    self.unknown_instruments += 1
                    databento_usage.record(
                        dataset="OPRA.PILLAR",
                        schema="trades",
                        mode="live",
                        consumer="opra-shadow",
                        unknown_instruments=1,
                    )
                return False
            if ts_event and self.last_event_ns and ts_event < self.last_event_ns:
                self.out_of_order += 1
            self.last_event_ns = max(self.last_event_ns, ts_event)
            price = _price(row.get("price"))
            # Trades-schema records carry no BBO; classify against the stored
            # tcbbo quote. A record that still carries its own BBO (tests,
            # replayed pre-migration rows) keeps using it.
            bid = _price(row.get("bid_px_00"))
            ask = _price(row.get("ask_px_00"))
            if bid is None and ask is None:
                bid, ask = self._last_bbo.get(instrument_id, (None, None))
            side, source = _quote_side(price, bid, ask)
            normalized = dict(row)
            normalized.update(
                {
                    "instrument_id": instrument_id,
                    "ts_event": ts_event,
                    "ts_source": event_source,
                    "price": price,
                    "size": row.get("size"),
                    "side": side,
                    "aggressor_source": source,
                    "bid_px_00": bid,
                    "ask_px_00": ask,
                }
            )
            self._trades.append(normalized)
            if len(self._seen_order) == self._seen_order.maxlen:
                self._seen.discard(self._seen_order[0])
            self._seen.add(key)
            self._seen_order.append(key)
            cutoff = max(0, self.last_event_ns - self.window_ns)
            # Out-of-order arrivals land at the RIGHT of this append-order deque, so a
            # left-prefix pop can leave a stale (pre-cutoff) trade behind a newer one at
            # index 0. Filter the whole window so a late old print is not retained and
            # emitted as a "current" UOA candidate. 2026-07-25.
            self._trades = deque(
                trade
                for trade in self._trades
                if _timestamp_ns(trade.get("ts_event")) >= cutoff
            )
            return True

    def build_snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        instant = now or datetime.now(UTC)
        with self._lock:
            trades = list(self._trades)
            definitions = [item[0] for item in self._definitions.values()]
            definition_times = {key: item[1] for key, item in self._definitions.items()}
            metrics = {
                "records_in_window": len(trades),
                "definition_count": len(definitions),
                "unknown_instruments": self.unknown_instruments,
                "pending_instruments": len(self._pending),
                "duplicates": self.duplicates,
                "out_of_order": self.out_of_order,
            }
        candidates = detect_unusual_options_activity(
            trades,
            definitions,
            min_premium=self.min_premium,
            tickers=self.hotlist,
        )
        clean: list[dict[str, Any]] = []
        now_ns = int(instant.timestamp() * 1_000_000_000)
        for candidate in candidates:
            raw = dict(candidate.pop("_opra_raw", {}) or {})
            instrument_id = int(raw.get("instrument_id") or 0)
            event_value = raw.get("ts_event")
            if event_value is None:
                event_value = raw.get("ts_recv")
            ts_ns = _timestamp_ns(event_value)
            source_row = raw
            definition_ts = definition_times.get(instrument_id, 0)
            candidate.update(
                {
                    "event_ts_ns": ts_ns,
                    "receive_ts_ns": _timestamp_ns(raw.get("ts_recv")),
                    "aggressor_source": source_row.get("aggressor_source", "unknown"),
                    "aggressor_confidence": 1.0
                    if source_row.get("aggressor_source") == "quote_rule"
                    else 0.0,
                    "nbbo_bid": source_row.get("bid_px_00"),
                    "nbbo_ask": source_row.get("ask_px_00"),
                    "definition_age_seconds": max(0.0, (ts_ns - definition_ts) / 1e9)
                    if definition_ts and ts_ns
                    else None,
                    "definition_known": True,
                    "data_age_seconds": max(0.0, (now_ns - ts_ns) / 1e9)
                    if ts_ns
                    else None,
                    "source_dataset": "OPRA.PILLAR",
                    "source_schema": "trades",
                    "shadow_only": True,
                }
            )
            clean.append(candidate)
        databento_usage.record(
            dataset="OPRA.PILLAR",
            schema="trades",
            mode="live",
            consumer="opra-shadow",
            candidates=len(clean),
        )
        return {
            "version": "opra-shadow/v1",
            "status": "shadow",
            "shadow_only": True,
            "asof": instant.isoformat(),
            "hotlist": sorted(self.hotlist),
            "source": {"dataset": "OPRA.PILLAR", "schema": "tcbbo", "mode": "live"},
            "metrics": metrics,
            "session_date": self.session_date,
            "candidates": clean,
        }
