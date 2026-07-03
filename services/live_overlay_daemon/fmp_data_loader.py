"""FMP (Financial Modeling Prep) Historical Data Loader.

Fetches OHLC data and macro indicators from FMP API.
Prepares data for ensemble backtesting.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
import requests
import json

logger = logging.getLogger(__name__)


class FMPDataLoader:
    """Load historical OHLC and macro data from FMP."""

    BASE_URL = "https://financialmodelingprep.com/api/v3"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize FMP loader.

        Args:
            api_key: FMP API key (or env var FMP_API_KEY)
        """
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise ValueError("FMP_API_KEY not provided and not in env")

        self.session = requests.Session()
        self.session.timeout = 30

        logger.info("[FMP] Initialized with API key (last 4 chars: ...%s)" % self.api_key[-4:])

    def get_historical_price(
        self,
        symbol: str,
        period: str = "1hour",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 5000,
    ) -> list[dict]:
        """Fetch historical OHLC data.

        Args:
            symbol: Stock symbol (e.g., "NVDA")
            period: "1min", "5min", "15min", "30min", "1hour", "4hour", "daily"
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            limit: Max candles to return

        Returns: List of OHLC dicts
        """
        logger.info(f"[FMP] Fetching {symbol} {period}...")

        url = f"{self.BASE_URL}/historical-chart/{period}/{symbol}"
        params = {"apikey": self.api_key, "limit": limit}

        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and "error" in data:
                raise ValueError(f"FMP API error: {data['error']}")

            if not data:
                logger.warning(f"No data returned for {symbol}")
                return []

            # Convert FMP format to backtest format
            candles = []
            for i, candle in enumerate(reversed(data)):  # Reverse to chronological order
                parsed = {
                    "bar_index": i,
                    "timestamp": candle.get("date"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": int(candle.get("volume", 0)),
                    "atr": None,  # Will calculate
                }
                candles.append(parsed)

            logger.info(f"[FMP] Loaded {len(candles)} candles")

            # Calculate ATR (14-period simple)
            self._calculate_atr(candles, period=14)

            return candles

        except Exception as e:
            logger.error(f"[FMP] Error fetching {symbol}: {e}")
            raise

    def get_intraday_price(
        self,
        symbol: str,
        interval: str = "1hour",
    ) -> list[dict]:
        """Fetch latest intraday data (last 100 candles).

        Args:
            symbol: Stock symbol
            interval: "1min", "5min", "15min", "30min", "1hour"

        Returns: List of OHLC dicts
        """
        return self.get_historical_price(symbol, period=interval, limit=100)

    def get_daily_price(
        self,
        symbol: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
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
        logger.info(f"[FMP] Fetching {indicator}...")

        url = f"{self.BASE_URL}/economic/{indicator}"
        params = {"apikey": self.api_key, "limit": limit}

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and "error" in data:
                logger.warning(f"Economic data not available: {indicator}")
                return []

            logger.info(f"[FMP] Loaded {len(data)} data points for {indicator}")
            return data

        except Exception as e:
            logger.error(f"[FMP] Error fetching {indicator}: {e}")
            return []

    def get_sofr_iorb_spread(
        self,
        from_date: Optional[str] = None,
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

        # Create lookup maps
        sofr_map = {item.get("date"): float(item.get("value", 0)) for item in sofr_data}
        iorb_map = {item.get("date"): float(item.get("value", 0)) for item in iorb_data}

        # Merge by date
        spread_map = {}
        for date in sofr_map:
            if date in iorb_map:
                spread_map[date] = (sofr_map[date], iorb_map[date])

        logger.info(f"[FMP] Loaded SOFR/IORB for {len(spread_map)} days")
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

        logger.info(f"[FMP] Mapped SOFR/IORB to {len(result)}/{len(candles)} candles")
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
        with open(filepath, "w") as f:
            json.dump(candles, f, indent=2)
        logger.info(f"[FMP] Saved {len(candles)} candles to {filepath}")

    def load_from_json(self, filepath: str) -> list[dict]:
        """Load candles from JSON file."""
        with open(filepath, "r") as f:
            candles = json.load(f)
        logger.info(f"[FMP] Loaded {len(candles)} candles from {filepath}")
        return candles


def main():
    """Example usage."""
    import sys

    # Initialize loader
    loader = FMPDataLoader()

    # Fetch NVDA 1h data (last 6 months)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

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
    loader.save_to_json(candles, "/tmp/nvda_1h.json")

    print(f"\n✅ Data ready for backtest:")
    print(f"   Candles: {len(candles)}")
    print(f"   Macro points: {len(macro_candles)}")
    print(f"   File: /tmp/nvda_1h.json")


if __name__ == "__main__":
    main()
