"""Databento A0-Fast shadow worker with gated PRE-A0 notification only."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from open_prep.a0_contract import A0ThresholdContext, decide_core_level
from open_prep.a0_parity_store import A0ParityJournal, shadow_decision_row
from open_prep.a0_stream_buffer import BoundedBarBuffer, BufferedBar
from open_prep.a0_stream_recovery import RecoveryStatus, recover_before_bar
from open_prep.a0_stream_state import A0StreamState, StreamApplyStatus, StreamReference
from open_prep.pre_a0_telemetry import PreA0Telemetry

from .history import DatabentoHistoricalBarsProvider
from .live_runtime import start_live_reader
from .pre_a0_runtime import PreA0Runtime, build_pre_a0_runtime
from .telemetry import DEFAULT_METRICS_HOST, A0FastTelemetry, start_metrics_server

logger = logging.getLogger(__name__)


def _shadow_mode() -> str:
    mode = os.getenv(
        "RT_A0_FAST_MODE",
        os.getenv("A0_FAST_MODE", "off"),
    ).strip().lower()
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


def _buffer_capacity(symbol_count: int) -> int:
    default = max(2_048, symbol_count * 4)
    capacity = int(os.getenv("A0_FAST_BUFFER_CAPACITY", str(default)))
    if capacity < 1 or capacity > 1_000_000:
        raise ValueError("A0_FAST_BUFFER_CAPACITY must be between 1 and 1000000")
    return capacity


def _metrics_port() -> int:
    port = int(os.getenv("A0_FAST_METRICS_PORT", "9108"))
    if port < 0 or port > 65_535:
        raise ValueError("A0_FAST_METRICS_PORT must be between 0 and 65535")
    return port


def _metrics_host() -> str:
    configured = os.getenv("A0_FAST_METRICS_HOST", DEFAULT_METRICS_HOST).strip()
    return configured or DEFAULT_METRICS_HOST


def _reconnect_backoff_seconds() -> float:
    value = float(os.getenv("A0_FAST_RECONNECT_BACKOFF_SECONDS", "5"))
    if value < 0.1 or value > 60.0:
        raise ValueError(
            "A0_FAST_RECONNECT_BACKOFF_SECONDS must be between 0.1 and 60"
        )
    return value


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


@dataclass(slots=True)
class _Processor:
    state: A0StreamState
    thresholds: A0ThresholdContext
    history: DatabentoHistoricalBarsProvider
    journal: A0ParityJournal
    telemetry: A0FastTelemetry
    pre_a0: PreA0Runtime | None = None
    recovery_retry_after: dict[str, float] = field(default_factory=dict)

    def process(self, item: BufferedBar) -> bool:
        """Process one bar; return True when a required resync is complete."""
        bar = item.bar
        symbol = bar.symbol.strip().upper()
        self.telemetry.record_processed()
        if item.resync_required:
            self.state.invalidate(symbol)
            if self.pre_a0 is not None:
                self.pre_a0.reset(symbol)
        try:
            result = self.state.apply(bar)
        except (TypeError, ValueError, OverflowError):
            logger.debug("A0-Fast rejected malformed stream bar", exc_info=True)
            return False

        recovered = False
        if result.status in (
            StreamApplyStatus.BOOTSTRAP_REQUIRED,
            StreamApplyStatus.GAP_DETECTED,
        ):
            if self.pre_a0 is not None:
                self.pre_a0.reset(symbol)
            retry_at = self.recovery_retry_after.get(symbol, 0.0)
            if time.monotonic() < retry_at:
                return False
            recovery = recover_before_bar(self.state, bar, self.history)
            self.telemetry.record_recovery(
                str(recovery.status), recovery.historical_bars
            )
            if recovery.status is not RecoveryStatus.RECOVERED:
                self.recovery_retry_after[symbol] = time.monotonic() + 30.0
                logger.warning(
                    "A0-Fast recovery failed for %s: status=%s error=%s",
                    symbol,
                    recovery.status,
                    recovery.error,
                )
                return False
            self.recovery_retry_after.pop(symbol, None)
            result = recovery.apply_result
            recovered = True
            self.telemetry.acknowledge_resync(symbol)
            logger.info(
                "A0-Fast recovered %s from %d historical bars (volume=%d)",
                symbol,
                recovery.historical_bars,
                recovery.recovered_volume,
            )
            if result is None:
                return recovered
        if result.status is not StreamApplyStatus.ACCEPTED or result.snapshot is None:
            return recovered
        if self.pre_a0 is not None:
            try:
                pre_result = self.pre_a0.process(result.snapshot)
                if pre_result.operator_payload is not None:
                    logger.info(
                        "PRE_A0_OBSERVE %s",
                        json.dumps(pre_result.operator_payload, sort_keys=True),
                    )
                    if str(self.pre_a0.config.pre_a0_mode) == "notify":
                        from open_prep import rt_notify

                        if rt_notify.notify_pre_a0(
                            pre_result.operator_payload,
                            on_budget_exceeded=(
                                self.pre_a0.telemetry.record_alert_budget_exceeded
                            ),
                        ):
                            self.pre_a0.telemetry.record_alert(
                                int(pre_result.operator_payload["horizon_s"]),
                                str(pre_result.operator_payload["direction"]),
                            )
            except (OSError, TypeError, ValueError, OverflowError):
                self.pre_a0.telemetry.record_runtime_error()
                logger.warning(
                    "PRE-A0 shadow processing failed for %s",
                    result.snapshot.market.symbol,
                    exc_info=True,
                )
        decision = decide_core_level(result.snapshot.market, self.thresholds)
        if decision.core_level != "A0":
            return recovered
        payload = shadow_decision_row(
            decision,
            self.thresholds,
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
            recorded = self.journal.record(payload)
        except (OSError, TypeError, ValueError):
            logger.warning(
                "A0-Fast parity persistence failed for %s",
                result.snapshot.market.symbol,
                exc_info=True,
            )
            return recovered
        if recorded:
            self.telemetry.record_decision()
            logger.info("A0_FAST_SHADOW %s", json.dumps(payload, sort_keys=True))
        return recovered


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
    thresholds = _thresholds()
    history = DatabentoHistoricalBarsProvider(api_key)
    journal = A0ParityJournal(_parity_log_dir(), source="databento")
    pre_a0_telemetry = PreA0Telemetry()
    telemetry = A0FastTelemetry(pre_a0=pre_a0_telemetry)
    pre_a0 = build_pre_a0_runtime(
        os.environ,
        thresholds=thresholds,
        telemetry=pre_a0_telemetry,
    )
    metrics_server = start_metrics_server(
        _metrics_port(),
        telemetry,
        host=_metrics_host(),
    )
    processor = _Processor(state, thresholds, history, journal, telemetry, pre_a0)
    capacity = _buffer_capacity(len(symbols))
    reconnect_backoff = _reconnect_backoff_seconds()
    backoff_event = threading.Event()

    import databento as db
    try:
        while not backoff_event.is_set():
            buffer = BoundedBarBuffer(capacity)
            telemetry.set_buffer(buffer.snapshot())
            reason = "connection_failed"
            try:
                reader = start_live_reader(
                    lambda: db.Live(key=api_key),
                    symbols=symbols,
                    buffer=buffer,
                    telemetry=telemetry,
                )
                logger.info(
                    "A0-Fast shadow reader started for %d symbols (buffer=%d)",
                    len(symbols),
                    capacity,
                )
                snapshot = buffer.snapshot()
                while not snapshot.closed:
                    item = buffer.take(timeout=0.5)
                    snapshot = buffer.snapshot()
                    telemetry.set_buffer(snapshot)
                    if snapshot.closed:
                        if item is not None:
                            telemetry.record_queue_drop()
                        break
                    if item is not None:
                        if item.resync_required:
                            telemetry.require_resync(item.bar.symbol)
                        if processor.process(item) and item.resync_required:
                            buffer.acknowledge_resync(item.bar.symbol)
                            telemetry.set_buffer(buffer.snapshot())
                    snapshot = buffer.snapshot()
                discarded = buffer.discard_all()
                telemetry.record_queue_drop(discarded)
                telemetry.set_buffer(buffer.snapshot())
                reason = snapshot.close_reason or "stream_ended"
                reader.join(timeout=5.0)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                logger.warning("A0-Fast connection cycle failed: %s", reason)
            telemetry.record_disconnect(reason)
            for symbol in symbols:
                state.invalidate(symbol)
                telemetry.require_resync(symbol)
                if pre_a0 is not None:
                    pre_a0.reset(symbol)
            logger.warning(
                "A0-Fast disconnected (%s); reconnecting in %.1fs",
                reason,
                reconnect_backoff,
            )
            backoff_event.wait(reconnect_backoff)
    except KeyboardInterrupt:
        logger.info("A0-Fast shutdown requested")
    finally:
        if pre_a0 is not None:
            try:
                pre_a0.flush()
            except (OSError, TypeError, ValueError):
                pre_a0.telemetry.record_persistence_error()
                logger.warning("PRE-A0 final snapshot flush failed", exc_info=True)
        if metrics_server is not None:
            metrics_server.shutdown()


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # A broad live subscription resolves every requested symbol. Databento
    # emits each mapping at INFO, which can exceed Railway's per-replica log
    # limit without providing actionable worker evidence.
    logging.getLogger("databento.live.client").setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    run()


if __name__ == "__main__":
    main()
