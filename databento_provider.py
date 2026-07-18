"""Provider abstraction for market data access.

Defines a ``MarketDataProvider`` protocol that decouples consumers from the
concrete Databento SDK.  Two implementations ship with this module:

* **DabentoProvider** – delegates to the real Databento Historical client.
* **DegradedProvider** – returns empty / ``None`` results (``get_range``
  raises ``RuntimeError``); for offline or test scenarios.

Usage::

    from databento_provider import MarketDataProvider, DabentoProvider, DegradedProvider

    provider = DabentoProvider(api_key=os.getenv("DATABENTO_API_KEY"))
    store = provider.get_range(
        context="my_pipeline",
        dataset="EQUS.MINI",
        symbols=["AAPL", "MSFT"],
        schema="ohlcv-1m",
        start="2024-01-02",
        end="2024-01-03",
    )
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from databento_utils import US_EASTERN_TZ

logger = logging.getLogger(__name__)


# ── Protocol ────────────────────────────────────────────────────────────────

@runtime_checkable
class MarketDataProvider(Protocol):
    """Minimal contract for fetching market-data time series."""

    def get_range(
        self,
        *,
        context: str,
        dataset: str,
        symbols: list[str],
        schema: str,
        start: str,
        end: str,
    ) -> Any:
        """Return a Databento-compatible store (supports ``.to_df()``)."""
        ...

    def get_schema_available_end(self, dataset: str, schema: str) -> pd.Timestamp | None:
        """Latest available timestamp for *dataset/schema*, or ``None``."""
        ...

    def list_datasets(self) -> list[str]:
        """Return the Databento catalog (legacy name; not entitlements)."""
        ...


# ── Databento-backed implementation ─────────────────────────────────────────

class DabentoProvider:
    """Delegates all calls to the real Databento Historical client."""

    def __init__(self, api_key: str | None = None) -> None:
        # Lazy import so the databento package is only required when
        # this provider is actually instantiated.
        from databento_client import _make_databento_client
        self._client = _make_databento_client(api_key)

    # -- protocol methods --------------------------------------------------

    def get_range(
        self,
        *,
        context: str,
        dataset: str,
        symbols: list[str],
        schema: str,
        start: str,
        end: str,
    ) -> Any:
        from databento_client import _databento_get_range_with_retry
        return _databento_get_range_with_retry(
            self._client,
            context=context,
            dataset=dataset,
            symbols=symbols,
            schema=schema,
            start=start,
            end=end,
        )

    def get_schema_available_end(self, dataset: str, schema: str) -> pd.Timestamp | None:
        from databento_client import _get_schema_available_end
        return _get_schema_available_end(self._client, dataset, schema)

    def list_datasets(self) -> list[str]:
        """Deprecated compatibility alias for :meth:`list_catalog_datasets`."""
        import warnings

        warnings.warn(
            "list_datasets() returns Databento's catalog, not account entitlements; "
            "use list_catalog_datasets()",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.list_catalog_datasets()

    def list_catalog_datasets(self) -> list[str]:
        from databento_access import list_catalog_datasets_from_client

        return list_catalog_datasets_from_client(self._client)

    def get_dataset_access_status(self, dataset: str):
        from databento_access import inspect_historical_access

        return inspect_historical_access(self._client, dataset)


# ── Degraded / offline fallback ─────────────────────────────────────────────

class DegradedProvider:
    """No-op provider that signals unavailability without crashing.

    ``get_range`` raises ``RuntimeError`` so callers can decide how to
    handle the absence of live data.  The other methods return safe empty
    values.
    """

    def get_range(
        self,
        *,
        context: str,
        dataset: str,
        symbols: list[str],
        schema: str,
        start: str,
        end: str,
    ) -> Any:
        raise RuntimeError(
            f"DegradedProvider: no market data backend available "
            f"(context={context}, dataset={dataset}, schema={schema})"
        )

    def get_schema_available_end(self, dataset: str, schema: str) -> pd.Timestamp | None:
        return None

    def list_datasets(self) -> list[str]:
        return []

    def list_catalog_datasets(self) -> list[str]:
        return []


# ── Module-level convenience ────────────────────────────────────────────────

def list_catalog_datasets(api_key: str | None = None) -> list[str]:
    """Return Databento's dataset catalog; this is not an entitlement list.

    Thin wrapper around ``DabentoProvider.list_catalog_datasets`` so callers
    don't need to instantiate a provider just to enumerate datasets.
    """
    return DabentoProvider(api_key).list_catalog_datasets()


def list_accessible_datasets(api_key: str | None = None) -> list[str]:
    """Deprecated alias returning the catalog, not accessible datasets."""
    import warnings

    warnings.warn(
        "list_accessible_datasets() was misleading and returns the global catalog; "
        "use list_catalog_datasets() or get_dataset_access_status()",
        DeprecationWarning,
        stacklevel=2,
    )
    return list_catalog_datasets(api_key)


def get_dataset_access_status(api_key: str | None, dataset: str):
    """Return truthful catalog and historical-range status for one dataset."""
    return DabentoProvider(api_key).get_dataset_access_status(dataset)


def list_recent_trading_days(
    api_key: str | None,
    *,
    dataset: str,
    lookback_days: int,
    end_date: date | None = None,
) -> list[date]:
    """Return the most recent available trading days for a Databento dataset.

    This is the provider-boundary replacement for direct imports from the
    screener monolith.
    """
    provider = DabentoProvider(api_key)
    current_market_day = datetime.now(US_EASTERN_TZ).date()
    anchor = end_date or current_market_day
    start_date = anchor - timedelta(days=max(lookback_days * 4, 90))
    conditions = provider._client.metadata.get_dataset_condition(
        dataset=dataset,
        start_date=start_date.isoformat(),
        end_date=anchor.isoformat(),
    )
    days = [
        date.fromisoformat(str(item.get("date")))
        for item in conditions
        if isinstance(item, dict) and item.get("condition") == "available"
    ]
    if end_date is None:
        days = [day for day in days if day < current_market_day]
    return days[-lookback_days:]
