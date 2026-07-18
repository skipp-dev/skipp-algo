"""Thread-safe Prometheus telemetry for the isolated A0-Fast worker."""

from __future__ import annotations

import resource
import threading
import time
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from open_prep.a0_stream_buffer import BufferSnapshot
from open_prep.pre_a0_telemetry import PreA0Telemetry

DEFAULT_METRICS_HOST = "127.0.0.1"


class A0FastTelemetry:
    def __init__(
        self,
        *,
        record_wire_bytes: int = 104,
        pre_a0: PreA0Telemetry | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._record_wire_bytes = max(0, int(record_wire_bytes))
        self._connected = False
        self._records_received = 0
        self._records_processed = 0
        self._wire_bytes = 0
        self._disconnects = 0
        self._decisions = 0
        self._recovery_counts: Counter[str] = Counter()
        self._historical_bars = 0
        self._queue_capacity = 0
        self._queue_depth = 0
        self._queue_high_watermark = 0
        self._queue_dropped = 0
        self._buffer_resync_required = 0
        self._forced_resync_symbols: set[str] = set()
        self._last_record_monotonic: float | None = None
        self._last_disconnect_reason = "none"
        self._pre_a0 = pre_a0

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = bool(connected)

    def record_received(self) -> None:
        with self._lock:
            self._records_received += 1
            self._wire_bytes += self._record_wire_bytes
            self._last_record_monotonic = time.monotonic()

    def record_processed(self) -> None:
        with self._lock:
            self._records_processed += 1

    def record_queue_drop(self, count: int = 1) -> None:
        with self._lock:
            self._queue_dropped += max(0, int(count))

    def record_disconnect(self, reason: str) -> None:
        with self._lock:
            self._disconnects += 1
            self._last_disconnect_reason = _metric_reason(reason)
            self._connected = False

    def record_recovery(self, status: str, historical_bars: int = 0) -> None:
        with self._lock:
            self._recovery_counts[_metric_reason(status)] += 1
            self._historical_bars += max(0, int(historical_bars))

    def record_decision(self) -> None:
        with self._lock:
            self._decisions += 1

    def require_resync(self, symbol: str) -> None:
        with self._lock:
            self._forced_resync_symbols.add(symbol.strip().upper())

    def acknowledge_resync(self, symbol: str) -> None:
        with self._lock:
            self._forced_resync_symbols.discard(symbol.strip().upper())

    def set_buffer(self, snapshot: BufferSnapshot) -> None:
        with self._lock:
            self._queue_capacity = snapshot.capacity
            self._queue_depth = snapshot.depth
            self._queue_high_watermark = max(
                self._queue_high_watermark, snapshot.high_watermark
            )
            self._buffer_resync_required = len(snapshot.resync_required_symbols)

    def snapshot(self, *, now_monotonic: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            age = (
                max(0.0, now - self._last_record_monotonic)
                if self._last_record_monotonic is not None
                else -1.0
            )
            return {
                "connected": self._connected,
                "records_received": self._records_received,
                "records_processed": self._records_processed,
                "wire_bytes": self._wire_bytes,
                "disconnects": self._disconnects,
                "decisions": self._decisions,
                "recovery_counts": dict(self._recovery_counts),
                "historical_bars": self._historical_bars,
                "queue_capacity": self._queue_capacity,
                "queue_depth": self._queue_depth,
                "queue_high_watermark": self._queue_high_watermark,
                "queue_dropped": self._queue_dropped,
                "resync_required": max(
                    self._buffer_resync_required,
                    len(self._forced_resync_symbols),
                ),
                "forced_resync_required": len(self._forced_resync_symbols),
                "last_record_age_seconds": age,
                "last_disconnect_reason": self._last_disconnect_reason,
                "process_cpu_seconds": time.process_time(),
                "process_peak_rss_bytes": _peak_rss_bytes(),
                "uptime_seconds": max(0.0, now - self._started_monotonic),
            }

    def health_status(self) -> tuple[HTTPStatus, str]:
        snapshot = self.snapshot()
        if not snapshot["connected"]:
            return HTTPStatus.SERVICE_UNAVAILABLE, "disconnected"
        if snapshot["resync_required"]:
            return HTTPStatus.SERVICE_UNAVAILABLE, "resync_required"
        return HTTPStatus.OK, "ok"

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        metrics = [
            _gauge("a0_fast_stream_connected", int(snapshot["connected"])),
            _counter("a0_fast_records_received_total", snapshot["records_received"]),
            _counter("a0_fast_records_processed_total", snapshot["records_processed"]),
            _counter("a0_fast_wire_bytes_total", snapshot["wire_bytes"]),
            _counter("a0_fast_disconnects_total", snapshot["disconnects"]),
            _counter("a0_fast_decisions_total", snapshot["decisions"]),
            _counter("a0_fast_historical_bars_total", snapshot["historical_bars"]),
            _gauge("a0_fast_queue_capacity", snapshot["queue_capacity"]),
            _gauge("a0_fast_queue_depth", snapshot["queue_depth"]),
            _gauge("a0_fast_queue_high_watermark", snapshot["queue_high_watermark"]),
            _counter("a0_fast_queue_dropped_total", snapshot["queue_dropped"]),
            _gauge("a0_fast_resync_required_symbols", snapshot["resync_required"]),
            _gauge(
                "a0_fast_forced_resync_required_symbols",
                snapshot["forced_resync_required"],
            ),
            _gauge(
                "a0_fast_last_record_age_seconds",
                snapshot["last_record_age_seconds"],
            ),
            _counter("a0_fast_process_cpu_seconds_total", snapshot["process_cpu_seconds"]),
            _gauge("a0_fast_process_peak_rss_bytes", snapshot["process_peak_rss_bytes"]),
            _gauge("a0_fast_uptime_seconds", snapshot["uptime_seconds"]),
        ]
        metrics.append("# TYPE a0_fast_recoveries_total counter\n")
        for status, count in sorted(snapshot["recovery_counts"].items()):
            metrics.append(
                f'a0_fast_recoveries_total{{status="{status}"}} {count}\n'
            )
        metrics.append("# TYPE a0_fast_last_disconnect_info gauge\n")
        metrics.append(
            "a0_fast_last_disconnect_info"
            f'{{reason="{snapshot["last_disconnect_reason"]}"}} 1\n'
        )
        rendered = "".join(metrics)
        if self._pre_a0 is not None:
            rendered += self._pre_a0.render_prometheus()
        return rendered


def start_metrics_server(
    port: int,
    telemetry: A0FastTelemetry,
    *,
    host: str = DEFAULT_METRICS_HOST,
) -> ThreadingHTTPServer | None:
    if port <= 0:
        return None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/metrics":
                self._write(HTTPStatus.OK, telemetry.render_prometheus())
                return
            if self.path == "/healthz":
                status, body = telemetry.health_status()
                self._write(status, body + "\n")
                return
            self._write(HTTPStatus.NOT_FOUND, "not found\n")

        def _write(self, status: HTTPStatus, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, int(port)), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _metric_reason(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "_-" else "_" for char in str(value))
    return cleaned[:80] or "unknown"


def _peak_rss_bytes() -> int:
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS reports bytes.
    return rss * 1024 if rss < 10_000_000 else rss


def _counter(name: str, value: int | float) -> str:
    return f"# TYPE {name} counter\n{name} {value}\n"


def _gauge(name: str, value: int | float) -> str:
    return f"# TYPE {name} gauge\n{name} {value}\n"
