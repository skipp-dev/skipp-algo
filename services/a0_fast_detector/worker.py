"""Databento A0-Fast shadow worker. No notification or publication path."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from open_prep.a0_contract import A0ThresholdContext, decide_core_level
from open_prep.a0_parity_store import A0ParityJournal, shadow_decision_row
from open_prep.a0_stream import DatabentoOhlcv1sAdapter
from open_prep.a0_stream_recovery import RecoveryStatus, recover_before_bar
from open_prep.a0_stream_state import A0StreamState, StreamApplyStatus, StreamReference

from .history import DatabentoHistoricalBarsProvider

logger = logging.getLogger(__name__)


def _shadow_mode() -> str:
    mode = os.getenv("A0_FAST_MODE", "off").strip().lower()
    if mode != "shadow":
        raise RuntimeError("A0_FAST_MODE must be exactly 'shadow'")
    return mode


def _symbols() -> list[str]:
    symbols = list(dict.fromkeys(
        symbol.strip().upper()
        for symbol in os.getenv("A0_FAST_SYMBOLS", "").split(",")
        if symbol.strip()
    ))
    if not symbols:
        raise RuntimeError("A0_FAST_SYMBOLS must contain an explicit symbol set")
    return symbols


def _thresholds() -> A0ThresholdContext:
    return A0ThresholdContext(
        a0_volume=float(os.getenv("A0_FAST_A0_VOLUME", "3.0")),
        a1_volume=float(os.getenv("A0_FAST_A1_VOLUME", "1.0")),
        a2_volume=float(os.getenv("A0_FAST_A2_VOLUME", "0.6")),
        a0_price=float(os.getenv("A0_FAST_A0_PRICE", "2.0")),
        a1_price=float(os.getenv("A0_FAST_A1_PRICE", "1.0")),
        a2_price=float(os.getenv("A0_FAST_A2_PRICE", "0.5")),
    )


def _parity_log_dir() -> Path:
    raw = os.getenv("A0_FAST_PARITY_LOG_DIR", "").strip()
    if not raw:
        raise RuntimeError("A0_FAST_PARITY_LOG_DIR must point to durable storage")
    return Path(raw)


def _load_references(path: Path) -> list[StreamReference]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("reference file must contain a JSON list")
    references = [StreamReference(**row) for row in payload if isinstance(row, dict)]
    if len(references) != len(payload):
        raise ValueError("reference file contains a non-object row")
    if any(not reference.is_valid_for(reference.symbol) for reference in references):
        raise ValueError("reference file contains invalid or non-Databento data")
    return references


def _symbol_from_record(record: Any, symbol_map: dict[int, str]) -> str | None:
    instrument_id = getattr(record, "instrument_id", None)
    if instrument_id is None:
        instrument_id = getattr(getattr(record, "hd", None), "instrument_id", None)
    return symbol_map.get(instrument_id) if instrument_id is not None else None


def run() -> None:
    """Consume OHLCV-1s and emit core-A0 candidates to logs in shadow only."""
    _shadow_mode()
    symbols = _symbols()
    api_key = os.environ["DATABENTO_API_KEY"]
    reference_path = Path(os.environ["A0_FAST_REFERENCE_FILE"])
    state = A0StreamState(
        max_gap_seconds=float(os.getenv("A0_FAST_MAX_GAP_SECONDS", "2"))
    )
    for reference in _load_references(reference_path):
        state.set_reference(reference)
    adapter = DatabentoOhlcv1sAdapter()
    thresholds = _thresholds()
    history = DatabentoHistoricalBarsProvider(api_key)
    journal = A0ParityJournal(_parity_log_dir(), source="databento")
    recovery_retry_after: dict[str, float] = {}

    import databento as db
    client = db.Live(key=api_key)
    client.subscribe(
        dataset="EQUS.MINI",
        schema="ohlcv-1s",
        symbols=symbols,
        stype_in="raw_symbol",
    )
    logger.info("A0-Fast shadow subscribed to %d explicit symbols", len(symbols))
    symbol_map: dict[int, str] = {}
    for record in client:
        record_type = type(record).__name__
        if record_type == "SymbolMappingMsg":
            instrument_id = getattr(record, "instrument_id", None)
            raw_symbol = getattr(record, "stype_out_symbol", None)
            if instrument_id is not None and raw_symbol:
                symbol_map[int(instrument_id)] = str(raw_symbol).strip().upper()
            continue
        if "OHLCV" not in record_type.upper() and "BAR" not in record_type.upper():
            continue
        symbol = _symbol_from_record(record, symbol_map)
        if symbol is None:
            continue
        try:
            bar = adapter.normalize(record, symbol=symbol)
            result = state.apply(bar)
        except (TypeError, ValueError, OverflowError):
            logger.debug("A0-Fast rejected malformed stream record", exc_info=True)
            continue
        if result.status in (
            StreamApplyStatus.BOOTSTRAP_REQUIRED,
            StreamApplyStatus.GAP_DETECTED,
        ):
            retry_at = recovery_retry_after.get(symbol, 0.0)
            if time.monotonic() < retry_at:
                continue
            recovery = recover_before_bar(state, bar, history)
            if recovery.status is not RecoveryStatus.RECOVERED:
                recovery_retry_after[symbol] = time.monotonic() + 30.0
                logger.warning(
                    "A0-Fast recovery failed for %s: status=%s error=%s",
                    symbol, recovery.status, recovery.error,
                )
                continue
            recovery_retry_after.pop(symbol, None)
            result = recovery.apply_result
            logger.info(
                "A0-Fast recovered %s from %d historical bars (volume=%d)",
                symbol, recovery.historical_bars, recovery.recovered_volume,
            )
            if result is None:
                continue
        if result.status is not StreamApplyStatus.ACCEPTED or result.snapshot is None:
            continue
        decision = decide_core_level(result.snapshot.market, thresholds)
        if decision.core_level != "A0":
            continue
        payload = shadow_decision_row(
            decision,
            thresholds,
            direction="LONG" if decision.snapshot.change_pct > 0 else "SHORT",
            decision_scope="core_only",
            cumulative_regular_volume=result.snapshot.cumulative_regular_volume,
            extra={
                "mode": "shadow",
                "gap_state": str(result.snapshot.gap_state),
                "reference_source": result.snapshot.reference_source,
                "reference_version": result.snapshot.reference_version,
                "corporate_action_version": result.snapshot.corporate_action_version,
            },
        )
        try:
            recorded = journal.record(payload)
        except (OSError, TypeError, ValueError):
            logger.warning(
                "A0-Fast parity persistence failed for %s",
                result.snapshot.market.symbol,
                exc_info=True,
            )
            continue
        if recorded:
            logger.info("A0_FAST_SHADOW %s", json.dumps(payload, sort_keys=True))


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run()


if __name__ == "__main__":
    main()
