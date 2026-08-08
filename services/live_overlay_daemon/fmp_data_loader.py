"""FMP (Financial Modeling Prep) Historical Data Loader.

Fetches OHLC data and macro indicators from FMP API.
Prepares data for ensemble backtesting.

Uses the FMP stable API endpoints (as of 2025):
  - https://financialmodelingprep.com/stable/historical-chart/{period}?symbol={symbol}
  - https://financialmodelingprep.com/stable/economic/{indicator}

This loader mirrors the pattern from open_prep.macro.FMPClient
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class FMPDataLoader:
    """Load historical OHLC and macro data from FMP stable API.

    Uses https://financialmodelingprep.com/stable/ endpoints
    which are the current, non-deprecated FMP endpoints.
    """

    STABLE_BASE_URL = "https://financialmodelingprep.com"

    def __init__(self, api_key: str | None = None):
        """Initialize FMP loader.

        Args:
            api_key: FMP API key (or env var FMP_API_KEY)
        """
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise ValueError("FMP_API_KEY not provided and not in env")

        self.session = httpx.Client(timeout=30.0, follow_redirects=True)

        logger.info("[FMP] Initialized with API key (last 4 chars: ...%s)", self.api_key[-4:])

    def _build_url(self, path: str, params: dict) -> str:
        """Build FMP URL with API key and parameters."""
        query = {k: v for k, v in params.items() if v is not None}
        if self.api_key:
            query["apikey"] = self.api_key

        base_url = self.STABLE_BASE_URL  # Use stable base
        if not query:
            return f"{base_url}{path}"
        return f"{base_url}{path}?{urlencode(query, doseq=True)}"

    # The /stable/historical-chart endpoint caps each response to roughly
    # 3 months of intraday bars regardless of the requested from/to span,
    # so longer ranges must be fetched in date chunks and stitched.
    _CHUNK_DAYS_BY_PERIOD: ClassVar[dict[str, int]] = {
        "1min": 2,
        "5min": 7,
        "15min": 20,
        "30min": 30,
        "1hour": 45,
        "4hour": 120,
    }

    def _fetch_chart_rows(
        self,
        symbol: str,
        period: str,
        from_date: str | None,
        to_date: str | None,
    ) -> list[dict]:
        """Single historical-chart request; returns raw FMP rows (newest first)."""
        path = f"/stable/historical-chart/{period}"
        params = {"symbol": symbol}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        url = self._build_url(path, params)

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "error" in data:
                    raise ValueError(f"FMP API error: {data['error']}")
                return data if isinstance(data, list) else []
            except Exception as e:
                last_exc = e
                if attempt == 0:
                    logger.warning("[FMP] Retry %s %s..%s: %s", symbol, from_date, to_date, e)
        raise last_exc  # type: ignore[misc]

    def get_historical_price(
        self,
        symbol: str,
        period: str = "1hour",
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        """Fetch historical OHLC data from FMP stable API.

        Ranges longer than the endpoint's per-request window are fetched in
        date chunks and stitched (deduped by timestamp, chronological).

        Args:
            symbol: Stock symbol (e.g., "NVDA")
            period: "1min", "5min", "15min", "30min", "1hour", "4hour", "1day" (not "daily")
            from_date: Start date (YYYY-MM-DD) - optional
            to_date: End date (YYYY-MM-DD) - optional
            limit: accepted for call-site compatibility; NOT currently applied
                   (the body returns every candle in the window — no truncation)

        Returns: List of OHLC dicts
        """
        logger.info("[FMP] Fetching %s %s...", symbol, period)

        try:
            chunk_days = self._CHUNK_DAYS_BY_PERIOD.get(period)
            if not from_date or not chunk_days:
                # No range (or daily data): single request as before
                raw_rows = self._fetch_chart_rows(symbol, period, from_date, to_date)
            else:
                # Keep all three tz-aware (UTC) so the chunk-loop comparisons
                # never mix naive/aware datetimes.
                start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=UTC)
                end = (
                    datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=UTC)
                    if to_date
                    else datetime.now(UTC)
                )
                raw_rows = []
                chunk_start = start
                n_chunks = 0
                while chunk_start <= end:
                    chunk_end = min(chunk_start + timedelta(days=chunk_days), end)
                    rows = self._fetch_chart_rows(
                        symbol,
                        period,
                        chunk_start.strftime("%Y-%m-%d"),
                        chunk_end.strftime("%Y-%m-%d"),
                    )
                    raw_rows.extend(rows)
                    n_chunks += 1
                    chunk_start = chunk_end + timedelta(days=1)
                logger.info("[FMP] %s: stitched %s chunks", symbol, n_chunks)

            if not raw_rows:
                logger.warning("No data returned for %s", symbol)
                return []

            # Dedupe by timestamp (chunk edges can overlap), then sort
            # chronologically. FMP timestamps are "YYYY-MM-DD HH:MM:SS",
            # so lexicographic order == chronological order.
            by_ts = {row.get("date"): row for row in raw_rows if row.get("date")}
            ordered = [by_ts[ts] for ts in sorted(by_ts)]

            # Convert FMP format to backtest format. Skip rows with
            # missing / non-finite OHLC so NaN/inf never reaches the
            # ATR calculation or the backtester.
            candles = []
            for candle in ordered:
                try:
                    # Indexed, not .get(default): a missing key coerced to 0.0
                    # is finite, so it would pass the check below as a real bar.
                    o = float(candle["open"])
                    h = float(candle["high"])
                    lo = float(candle["low"])
                    c = float(candle["close"])
                    vol = int(candle.get("volume", 0) or 0)
                except (KeyError, TypeError, ValueError):
                    continue
                if not all(math.isfinite(v) for v in (o, h, lo, c)):
                    continue
                candles.append({
                    "bar_index": len(candles),
                    "timestamp": candle.get("date"),
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": vol,
                    "atr": None,  # Will calculate
                })

            logger.info("[FMP] Loaded %s candles", len(candles))

            # Calculate ATR (14-period simple)
            self._calculate_atr(candles, period=14)

            return candles

        except Exception as e:
            logger.error("[FMP] Error fetching %s: %s", symbol, e)
            raise

    def get_intraday_price(
        self,
        symbol: str,
        interval: str = "1hour",
    ) -> list[dict]:
        """Fetch latest intraday data for ``interval`` (returns the full window;
        the ``limit=100`` below is currently a no-op — see get_historical_price).

        Args:
            symbol: Stock symbol
            interval: "1min", "5min", "15min", "30min", "1hour"

        Returns: List of OHLC dicts
        """
        return self.get_historical_price(symbol, period=interval, limit=100)

    def get_daily_price(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """Fetch daily OHLC data.

        Args:
            symbol: Stock symbol
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns: List of daily OHLC dicts
        """
        return self.get_historical_price(
            symbol,
            period="daily",
            from_date=from_date,
            to_date=to_date,
            limit=5000,
        )

    def get_economic_data(
        self,
        indicator: str,
        limit: int = 500,
    ) -> list[dict]:
        """Fetch economic indicators (SOFR, IORB, etc).

        Args:
            indicator: "sofr", "iorb", "inflation-rate", "unemployment-rate"
            limit: Max data points

        Returns: List of {date, value} dicts
        """
        logger.info("[FMP] Fetching %s...", indicator)

        path = f"/stable/economic/{indicator}"
        params = {"limit": limit}
        url = self._build_url(path, params)

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and "error" in data:
                logger.warning("Economic data not available: %s", indicator)
                return []

            logger.info("[FMP] Loaded %s data points for %s", len(data), indicator)
            return data

        except Exception as e:
            logger.error("[FMP] Error fetching %s: %s", indicator, e)
            return []

    def get_sofr_iorb_spread(
        self,
        from_date: str | None = None,
    ) -> dict[str, tuple[float, float]]:
        """Get SOFR and IORB rates, return as daily spread.

        Args:
            from_date: Start date for data (YYYY-MM-DD)

        Returns: {date_str: (sofr_rate, iorb_rate)}
        """
        logger.info("[FMP] Fetching SOFR/IORB data...")

        sofr_data = self.get_economic_data("sofr", limit=500)
        iorb_data = self.get_economic_data("iorb", limit=500)

        if not sofr_data or not iorb_data:
            logger.warning("Could not fetch SOFR/IORB data")
            return {}

        # Create lookup maps; drop missing / non-finite values so a null
        # or NaN rate never reaches the spread computation.
        def _finite(raw) -> float | None:
            try:
                val = float(raw)
            except (TypeError, ValueError):
                return None
            return val if math.isfinite(val) else None

        sofr_map = {
            item.get("date"): v
            for item in sofr_data
            if item.get("date") and (v := _finite(item.get("value"))) is not None
        }
        iorb_map = {
            item.get("date"): v
            for item in iorb_data
            if item.get("date") and (v := _finite(item.get("value"))) is not None
        }

        # Merge by date
        spread_map = {}
        for date in sofr_map:
            if date in iorb_map:
                spread_map[date] = (sofr_map[date], iorb_map[date])

        logger.info("[FMP] Loaded SOFR/IORB for %s days", len(spread_map))
        return spread_map

    def map_macro_to_candles(
        self,
        candles: list[dict],
        sofr_iorb_map: dict[str, tuple[float, float]],
    ) -> dict[int, tuple[float, float]]:
        """Map SOFR/IORB daily data to OHLC bar indices.

        Args:
            candles: OHLC candles with 'timestamp' field
            sofr_iorb_map: {date_str: (sofr, iorb)}

        Returns: {bar_index: (sofr, iorb)}
        """
        result = {}

        for candle in candles:
            timestamp = candle.get("timestamp")
            if not timestamp:
                continue

            # Extract date (YYYY-MM-DD)
            if isinstance(timestamp, str):
                date_str = timestamp.split(" ")[0] if " " in timestamp else timestamp[:10]
            else:
                date_str = str(timestamp)[:10]

            # Look up SOFR/IORB for this date
            if date_str in sofr_iorb_map:
                result[candle["bar_index"]] = sofr_iorb_map[date_str]

        logger.info("[FMP] Mapped SOFR/IORB to %s/%s candles", len(result), len(candles))
        return result

    @staticmethod
    def _calculate_atr(candles: list[dict], period: int = 14) -> None:
        """Calculate ATR (Average True Range) and add to candles.

        Modifies candles in-place.
        """
        for i, candle in enumerate(candles):
            if i == 0:
                candle["atr"] = candle["high"] - candle["low"]
                continue

            prev_close = candles[i - 1]["close"]
            high = candle["high"]
            low = candle["low"]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )

            # Simple moving average of TR
            if i < period:
                candle["atr"] = tr
            else:
                prev_atr = candles[i - 1].get("atr", tr)
                candle["atr"] = (prev_atr * (period - 1) + tr) / period

    def save_to_json(self, candles: list[dict], filepath: str) -> None:
        """Save candles to JSON file."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(candles, f, indent=2)
        logger.info("[FMP] Saved %s candles to %s", len(candles), filepath)

    def load_from_json(self, filepath: str) -> list[dict]:
        """Load candles from JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            candles = json.load(f)
        logger.info("[FMP] Loaded %s candles from %s", len(candles), filepath)
        return candles

    def get_quote(self, symbol: str) -> float | None:
        """Fetch the latest price for ``symbol`` from the stable ``/quote`` endpoint.

        Suited to slow-moving single values (e.g. the ``^VIX`` index level) that
        do not warrant a full historical-chart pull. Returns the finite ``price``
        field, or ``None`` on any error / missing / non-finite value so callers
        can keep their last known value rather than propagate a bad reading.
        """
        url = self._build_url("/stable/quote", {"symbol": symbol})
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            row = data[0] if isinstance(data, list) and data else data
            if not isinstance(row, dict) or row.get("price") is None:
                return None
            price = float(row["price"])
            return price if math.isfinite(price) else None
        except Exception as e:
            logger.warning("[FMP] quote fetch failed for %s: %s", symbol, e)
            return None


def main():
    """Example usage."""

    # Initialize loader
    loader = FMPDataLoader()

    # Fetch NVDA 1h data (last 6 months)
    end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = (datetime.now(UTC) - timedelta(days=180)).strftime("%Y-%m-%d")

    print(f"[Backtest] Fetching NVDA data from {start_date} to {end_date}...")
    candles = loader.get_historical_price(
        symbol="NVDA",
        period="1hour",
        from_date=start_date,
        to_date=end_date,
        limit=5000,
    )

    print(f"[Backtest] Loaded {len(candles)} candles")

    # Fetch SOFR/IORB
    print("[Backtest] Fetching SOFR/IORB data...")
    sofr_iorb_map = loader.get_sofr_iorb_spread(from_date=start_date)

    # Map to candles
    print("[Backtest] Mapping macro data...")
    macro_candles = loader.map_macro_to_candles(candles, sofr_iorb_map)

    # Save for backtest
    output_path = "artifacts/dev/nvda_1h.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    loader.save_to_json(candles, output_path)

    print("\n✅ Data ready for backtest:")
    print(f"   Candles: {len(candles)}")
    print(f"   Macro points: {len(macro_candles)}")
    print(f"   File: {output_path}")


if __name__ == "__main__":
    main()
