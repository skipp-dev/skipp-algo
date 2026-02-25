"""Realtime signal engine — FMP-polling breakout detector with A0/A1 alerting.

Monitors top-N ranked candidates from the latest open_prep run, polls FMP
at a configurable interval (default 45 s), and detects breakout signals.

Signal Levels
-------------
  A0 — Immediate action: strong breakout confirmed with volume.
  A1 — Watch closely: early breakout pattern forming, pre-confirmation.

Usage::

    # Standalone polling loop (runs forever, writes signals to JSON)
    python -m open_prep.realtime_signals --interval 45

    # As a library (for Streamlit integration)
    from open_prep.realtime_signals import RealtimeEngine
    engine = RealtimeEngine(poll_interval=45, top_n=10)
    engine.poll_once()  # single iteration
    signals = engine.get_active_signals()
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .macro import FMPClient
from .signal_decay import adaptive_freshness_decay, adaptive_half_life
from .technical_analysis import detect_breakout
from .utils import to_float as _safe_float

logger = logging.getLogger("open_prep.realtime_signals")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_ARTIFACTS_LATEST = Path("artifacts/open_prep/latest")
SIGNALS_PATH = _ARTIFACTS_LATEST / "latest_realtime_signals.json"
LATEST_RUN_PATH = _ARTIFACTS_LATEST / "latest_open_prep_run.json"

# Backward-compat: also check old location in package dir
_LEGACY_RUN_PATH = Path(__file__).resolve().parent / "latest_open_prep_run.json"
DEFAULT_POLL_INTERVAL = 45  # seconds
DEFAULT_TOP_N = 10

# Signal level thresholds
A0_VOLUME_RATIO_MIN = 3.0        # 3x avg volume for A0
A1_VOLUME_RATIO_MIN = 1.5        # 1.5x for A1
A0_PRICE_CHANGE_PCT_MIN = 1.5    # 1.5% move for A0
A1_PRICE_CHANGE_PCT_MIN = 0.5    # 0.5% for A1

# Signal expiry
MAX_SIGNAL_AGE_SECONDS = 1800    # 30 min


@dataclass
class RealtimeSignal:
    """A single realtime breakout signal."""
    symbol: str
    level: str                        # "A0" or "A1"
    direction: str                    # "LONG", "SHORT", "B_UP", "B_DOWN"
    pattern: str                      # from detect_breakout
    price: float
    prev_close: float
    change_pct: float
    volume_ratio: float
    score: float                      # from v2 ranking (if available)
    confidence_tier: str              # from v2 ranking
    atr_pct: float
    freshness: float                  # 0..1 (signal strength decay)
    fired_at: str                     # ISO timestamp
    fired_epoch: float                # unix timestamp for sorting/expiry
    details: dict[str, Any] = field(default_factory=dict)
    symbol_regime: str = "NEUTRAL"
    # ── News catalyst enrichment (from newsstack_fmp) ──
    news_score: float = 0.0
    news_category: str = ""
    news_headline: str = ""
    news_warn_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self, now_epoch: float | None = None) -> bool:
        now = now_epoch or time.time()
        return (now - self.fired_epoch) > MAX_SIGNAL_AGE_SECONDS


class RealtimeEngine:
    """FMP-polling breakout detection engine."""

    def __init__(
        self,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        top_n: int = DEFAULT_TOP_N,
        fmp_client: FMPClient | None = None,
    ):
        self.poll_interval = max(10, poll_interval)
        self.top_n = top_n
        self._client = fmp_client
        self._client_disabled_reason: str | None = None
        self._active_signals: list[RealtimeSignal] = []
        self._watchlist: list[dict[str, Any]] = []  # top-N from latest run
        self._last_prices: dict[str, float] = {}
        self._load_watchlist()
        self._restore_signals_from_disk()

    # ------------------------------------------------------------------
    # Restore non-expired signals from previous run (dedup across restarts)
    # ------------------------------------------------------------------
    def _restore_signals_from_disk(self) -> None:
        """Load previously persisted signals to avoid re-firing on restart."""
        try:
            data = self.load_signals_from_disk()
            now_epoch = time.time()
            for raw in data.get("signals", []):
                fired_epoch = float(raw.get("fired_epoch", 0))
                if (now_epoch - fired_epoch) > MAX_SIGNAL_AGE_SECONDS:
                    continue  # already expired
                sig = RealtimeSignal(
                    symbol=str(raw.get("symbol", "")),
                    level=str(raw.get("level", "A1")),
                    direction=str(raw.get("direction", "LONG")),
                    pattern=str(raw.get("pattern", "")),
                    price=float(raw.get("price", 0)),
                    prev_close=float(raw.get("prev_close", 0)),
                    change_pct=float(raw.get("change_pct", 0)),
                    volume_ratio=float(raw.get("volume_ratio", 0)),
                    score=float(raw.get("score", 0)),
                    confidence_tier=str(raw.get("confidence_tier", "STANDARD")),
                    atr_pct=float(raw.get("atr_pct", 0)),
                    freshness=float(raw.get("freshness", 0)),
                    fired_at=str(raw.get("fired_at", "")),
                    fired_epoch=fired_epoch,
                    details=raw.get("details") or {},
                    symbol_regime=str(raw.get("symbol_regime", "NEUTRAL")),
                    news_score=float(raw.get("news_score", 0.0)),
                    news_category=str(raw.get("news_category", "")),
                    news_headline=str(raw.get("news_headline", "")),
                    news_warn_flags=list(raw.get("news_warn_flags") or []),
                )
                self._active_signals.append(sig)
            if self._active_signals:
                logger.info(
                    "Restored %d non-expired signal(s) from disk",
                    len(self._active_signals),
                )
        except Exception as exc:
            logger.debug("Could not restore signals from disk: %s", exc)

    @property
    def client(self) -> FMPClient:
        if self._client is None:
            try:
                self._client = FMPClient.from_env()
            except Exception as exc:
                # Fail-open: disable polling if API key missing or client cannot be built
                self._client_disabled_reason = str(exc)
                raise
        return self._client

    # ------------------------------------------------------------------
    # Load top-N symbols from latest open_prep run
    # ------------------------------------------------------------------
    def _load_watchlist(self) -> None:
        """Load top-N candidates from the latest pipeline result."""
        run_path = LATEST_RUN_PATH if LATEST_RUN_PATH.exists() else _LEGACY_RUN_PATH
        if not run_path.exists():
            logger.warning("No latest_open_prep_run.json found — watchlist empty")
            return
        try:
            with open(run_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ranked_v2 = data.get("ranked_v2") or []
            # Take top_n by score (already sorted)
            self._watchlist = ranked_v2[:self.top_n]
            logger.info(
                "Loaded %d symbols for realtime monitoring: %s",
                len(self._watchlist),
                [r.get("symbol") for r in self._watchlist],
            )
        except Exception as exc:
            logger.warning("Failed to load watchlist: %s", exc)

    def reload_watchlist(self) -> None:
        """Reload watchlist from latest pipeline run."""
        self._load_watchlist()

    # ------------------------------------------------------------------
    # Fetch current quotes for watched symbols
    # ------------------------------------------------------------------
    def _fetch_realtime_quotes(self) -> dict[str, dict[str, Any]]:
        """Fetch current quotes for all watched symbols via FMP batch quote."""
        if self._client_disabled_reason:
            return {}
        if not self._watchlist:
            return {}
        symbols = [str(r.get("symbol", "")).strip().upper() for r in self._watchlist if r.get("symbol")]
        if not symbols:
            return {}

        quotes: dict[str, dict[str, Any]] = {}
        try:
            # FMP batch quote endpoint
            raw = self.client.get_batch_quotes(symbols)
            for q in raw:
                sym = str(q.get("symbol", "")).strip().upper()
                if sym:
                    quotes[sym] = q
        except Exception as exc:
            logger.warning("Failed to fetch realtime quotes: %s", exc)
            # Fallback — individual quotes via batch API
            for sym in symbols:
                try:
                    q_list = self.client.get_batch_quotes([sym])
                    if q_list and isinstance(q_list, list) and q_list:
                        quotes[sym] = q_list[0]
                except Exception:
                    pass
        return quotes

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------
    def _detect_signal(
        self,
        symbol: str,
        quote: dict[str, Any],
        watchlist_entry: dict[str, Any],
    ) -> RealtimeSignal | None:
        """Analyze a single symbol's current quote for breakout signals."""
        price = _safe_float(quote.get("price") or quote.get("lastPrice"), 0.0)
        prev_close = _safe_float(quote.get("previousClose"), 0.0)
        volume = _safe_float(quote.get("volume"), 0.0)
        avg_volume = _safe_float(
            quote.get("avgVolume") or watchlist_entry.get("avg_volume"), 1.0
        )

        if price <= 0 or prev_close <= 0:
            return None

        change_pct = ((price / prev_close) - 1) * 100
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        atr_pct = _safe_float(watchlist_entry.get("atr_pct_computed") or watchlist_entry.get("atr_pct"), 0.0)
        confidence_tier = str(watchlist_entry.get("confidence_tier", "STANDARD"))
        v2_score = _safe_float(watchlist_entry.get("score"), 0.0)
        symbol_regime = str(watchlist_entry.get("symbol_regime", "NEUTRAL"))

        # Check for significant price movement
        abs_change = abs(change_pct)

        # Determine signal level
        level: str | None = None
        if volume_ratio >= A0_VOLUME_RATIO_MIN and abs_change >= A0_PRICE_CHANGE_PCT_MIN:
            level = "A0"
        elif volume_ratio >= A1_VOLUME_RATIO_MIN and abs_change >= A1_PRICE_CHANGE_PCT_MIN:
            level = "A1"
        elif abs_change >= A0_PRICE_CHANGE_PCT_MIN * 1.5:
            # Very large move even without volume confirmation
            level = "A1"

        if level is None:
            return None

        # Determine direction
        direction = "LONG" if change_pct > 0 else "SHORT"
        pattern = "realtime_momentum"

        # Check previous price for reversal pattern
        prev_price = self._last_prices.get(symbol)
        if prev_price is not None:
            if prev_price < prev_close and price > prev_close:
                pattern = "realtime_reversal_up"
                direction = "LONG"
            elif prev_price > prev_close and price < prev_close:
                pattern = "realtime_reversal_down"
                direction = "SHORT"

        # Breakout from key levels
        pdh = _safe_float(watchlist_entry.get("pdh"), 0.0)
        pdl = _safe_float(watchlist_entry.get("pdl"), 0.0)
        if pdh > 0 and price > pdh and (prev_price is None or prev_price <= pdh):
            pattern = "pdh_breakout"
            direction = "LONG"
            if level == "A1":
                level = "A0"  # PDH breakout upgrades to A0
        if pdl > 0 and price < pdl and (prev_price is None or prev_price >= pdl):
            pattern = "pdl_breakdown"
            direction = "SHORT"
            if level == "A1":
                level = "A0"

        now = datetime.now(timezone.utc)
        return RealtimeSignal(
            symbol=symbol,
            level=level,
            direction=direction,
            pattern=pattern,
            price=round(price, 2),
            prev_close=round(prev_close, 2),
            change_pct=round(change_pct, 2),
            volume_ratio=round(volume_ratio, 2),
            score=round(v2_score, 3),
            confidence_tier=confidence_tier,
            atr_pct=round(atr_pct, 2),
            freshness=1.0,  # brand new signal
            fired_at=now.isoformat(),
            fired_epoch=now.timestamp(),
            details={
                "pdh": pdh,
                "pdl": pdl,
                "volume": volume,
                "avg_volume": avg_volume,
            },
            symbol_regime=symbol_regime,
        )

    # ------------------------------------------------------------------
    # Poll once — main detection loop
    # ------------------------------------------------------------------
    def poll_once(self) -> list[RealtimeSignal]:
        """Run one poll cycle: fetch quotes → detect signals → persist.

        Also polls the FMP newsstack on each cycle and enriches signals
        with ``news_score``, ``news_category``, and ``news_headline``.
        """
        if self._client_disabled_reason:
            # Persist empty signals with disabled reason so UIs stay green
            self._active_signals.clear()
            self._save_signals(disabled_reason=self._client_disabled_reason)
            return []

        # ── Newsstack poll (synchronous, fail-open) ─────────────
        news_by_ticker: dict[str, dict[str, Any]] = {}
        try:
            from newsstack_fmp.pipeline import poll_once as _newsstack_poll
            from newsstack_fmp.config import Config as _NSConfig

            ns_candidates = _newsstack_poll(_NSConfig())
            for nc in ns_candidates:
                tk = str(nc.get("ticker", "")).strip().upper()
                if tk:
                    # Keep the highest-score candidate per ticker
                    prev = news_by_ticker.get(tk)
                    if prev is None or nc.get("news_score", 0) > prev.get("news_score", 0):
                        news_by_ticker[tk] = nc
        except Exception as exc:
            logger.debug("Newsstack poll skipped: %s", exc)

        new_signals: list[RealtimeSignal] = []

        quotes = self._fetch_realtime_quotes()
        if not quotes:
            logger.debug("No quotes received in poll cycle")
            return new_signals

        # Build symbol→watchlist entry map
        wl_map = {
            str(r.get("symbol", "")).strip().upper(): r
            for r in self._watchlist if r.get("symbol")
        }

        for sym, quote in quotes.items():
            wl_entry = wl_map.get(sym, {})
            signal = self._detect_signal(sym, quote, wl_entry)
            if signal:
                # Enrich with newsstack data
                ns_data = news_by_ticker.get(sym)
                if ns_data:
                    signal.news_score = _safe_float(ns_data.get("news_score", 0))
                    signal.news_category = str(ns_data.get("category", ""))
                    signal.news_headline = str(ns_data.get("headline", ""))[:200]
                    signal.news_warn_flags = list(ns_data.get("warn_flags") or [])
                    # Upgrade A1 → A0 if news catalyst is strong
                    if signal.level == "A1" and signal.news_score >= 0.80:
                        signal.level = "A0"
                        signal.details["a0_upgrade_reason"] = "news_catalyst"

                # Check if we already have an active signal for this symbol
                existing = [s for s in self._active_signals if s.symbol == sym and not s.is_expired()]
                if existing:
                    # Only add if new signal is higher level or different direction
                    latest = existing[-1]
                    if signal.level == "A0" and latest.level == "A1":
                        # Upgrade: remove old A1, add A0
                        self._active_signals = [s for s in self._active_signals if s.symbol != sym]
                        new_signals.append(signal)
                    elif signal.direction != latest.direction:
                        # Direction change: replace
                        self._active_signals = [s for s in self._active_signals if s.symbol != sym]
                        new_signals.append(signal)
                    # else: same level/direction — skip (already signaled)
                else:
                    new_signals.append(signal)

            # Track price for next cycle
            price = _safe_float(quote.get("price") or quote.get("lastPrice"), 0.0)
            if price > 0:
                self._last_prices[sym] = price

        # Add new signals to active list
        self._active_signals.extend(new_signals)

        # Decay existing signals
        now_epoch = time.time()
        for sig in self._active_signals:
            elapsed = now_epoch - sig.fired_epoch
            sig.freshness = adaptive_freshness_decay(
                elapsed, atr_pct=sig.atr_pct if sig.atr_pct > 0 else None,
            )

        # Prune expired signals
        self._active_signals = [s for s in self._active_signals if not s.is_expired()]

        # Sort: A0 before A1, then by freshness
        self._active_signals.sort(
            key=lambda s: (0 if s.level == "A0" else 1, -s.freshness),
        )

        # Persist
        self._save_signals()

        if new_signals:
            logger.info(
                "New signals: %s",
                [(s.symbol, s.level, s.direction, s.pattern) for s in new_signals],
            )

        return new_signals

    # ------------------------------------------------------------------
    # Signal access
    # ------------------------------------------------------------------
    def get_active_signals(self) -> list[RealtimeSignal]:
        """Return active (non-expired) signals, sorted by priority."""
        now_epoch = time.time()
        # Update freshness before returning
        for sig in self._active_signals:
            elapsed = now_epoch - sig.fired_epoch
            sig.freshness = adaptive_freshness_decay(
                elapsed, atr_pct=sig.atr_pct if sig.atr_pct > 0 else None,
            )
        self._active_signals = [s for s in self._active_signals if not s.is_expired()]
        return list(self._active_signals)

    def get_a0_signals(self) -> list[RealtimeSignal]:
        """Return only A0 (immediate action) signals."""
        return [s for s in self.get_active_signals() if s.level == "A0"]

    def get_a1_signals(self) -> list[RealtimeSignal]:
        """Return only A1 (watch closely) signals."""
        return [s for s in self.get_active_signals() if s.level == "A1"]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_signals(self, *, disabled_reason: str | None = None) -> None:
        """Write active signals to JSON for dashboard consumption."""
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_epoch": time.time(),
            "poll_interval": self.poll_interval,
            "watched_symbols": [str(r.get("symbol", "")) for r in self._watchlist],
            "signals": [s.to_dict() for s in self._active_signals],
            "signal_count": len(self._active_signals),
            "a0_count": sum(1 for s in self._active_signals if s.level == "A0"),
            "a1_count": sum(1 for s in self._active_signals if s.level == "A1"),
            "disabled_reason": disabled_reason,
        }
        try:
            SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=SIGNALS_PATH.parent, suffix=".tmp", prefix="signals_",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2, default=str)
                    fh.write("\n")
                os.replace(tmp_path, SIGNALS_PATH)
            except BaseException:
                # Clean up temp file on any failure (including KeyboardInterrupt)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning("Failed to save signals: %s", exc)

    @staticmethod
    def load_signals_from_disk() -> dict[str, Any]:
        """Load latest signals from JSON (for Streamlit/VisiData)."""
        if not SIGNALS_PATH.exists():
            return {"signals": [], "signal_count": 0, "a0_count": 0, "a1_count": 0}
        try:
            with open(SIGNALS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {"signals": [], "signal_count": 0, "a0_count": 0, "a1_count": 0}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the realtime signal engine as a standalone polling loop."""
    import argparse

    parser = argparse.ArgumentParser(description="Realtime signal engine")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL, help="Poll interval in seconds")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Number of symbols to monitor")
    parser.add_argument("--reload-interval", type=int, default=300, help="Seconds between watchlist reloads")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    )

    engine = RealtimeEngine(poll_interval=args.interval, top_n=args.top_n)
    logger.info("Starting realtime signal engine (interval=%ds, top_n=%d)", args.interval, args.top_n)

    last_reload = time.time()
    while True:
        try:
            # Periodically reload watchlist from latest pipeline run
            if time.time() - last_reload > args.reload_interval:
                engine.reload_watchlist()
                last_reload = time.time()

            new_signals = engine.poll_once()

            active = engine.get_active_signals()
            a0 = [s for s in active if s.level == "A0"]
            a1 = [s for s in active if s.level == "A1"]
            logger.info(
                "Poll complete — %d active signals (%d A0, %d A1)",
                len(active), len(a0), len(a1),
            )

            if a0:
                for s in a0:
                    logger.info(
                        "🔴 A0 %s %s %s @ $%.2f (vol×%.1f, Δ%+.1f%%, fresh=%.0f%%)",
                        s.symbol, s.direction, s.pattern, s.price,
                        s.volume_ratio, s.change_pct, s.freshness * 100,
                    )

            time.sleep(args.interval)

        except KeyboardInterrupt:
            logger.info("Realtime engine stopped by user")
            break
        except Exception as exc:
            logger.error("Poll error: %s", exc, exc_info=True)
            time.sleep(max(10, args.interval))


if __name__ == "__main__":
    main()
