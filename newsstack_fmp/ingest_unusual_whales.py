"""Unusual Whales API adapter — options flow ingestion.

Replaces the retired Benzinga ``options_activity`` endpoint for
unusual options activity (UOA) consumers.

Auth
----
Reads ``UNUSUAL_WHALES_API_KEY`` from the environment.  Bearer
auth is sent as ``Authorization: Bearer <key>``.

Plan note
---------
Personal-use restriction applies on Basic/Advanced tiers per UW ToS.

Public docs: https://api.unusualwhales.com/docs
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Base URL for all UW REST endpoints.
UW_BASE_URL = "https://api.unusualwhales.com/api"

# Endpoint paths (kept as constants for grep/refactor).
UW_FLOW_ALERTS_PATH = "/option-trades/flow-alerts"
UW_FLOW_RECENT_PATH = "/stock/{ticker}/flow-recent"


class UnusualWhalesAdapter:
    """Synchronous adapter for the Unusual Whales REST API.

    Designed as a drop-in replacement for the Benzinga
    ``options_activity`` adapter call shape.  Returns flat list[dict]
    records mapped onto a Benzinga-compatible field set so existing
    dashboards keep rendering.
    """

    def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
        if not api_key:
            raise RuntimeError("UNUSUAL_WHALES_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

    def close(self) -> None:
        self.client.close()

    # ── Internal ────────────────────────────────────────────

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{UW_BASE_URL}{path}"
        try:
            r = self.client.get(url, params=params or {})
        except httpx.HTTPError as exc:
            logger.warning("UW HTTP error on %s: %s", path, exc)
            return None
        if r.status_code == 401:
            logger.error("UW auth failed (401) — check UNUSUAL_WHALES_API_KEY")
            return None
        if r.status_code == 403:
            logger.warning("UW 403 on %s — endpoint not in current plan tier", path)
            return None
        if r.status_code == 429:
            logger.warning("UW rate-limited (429) on %s", path)
            return None
        if r.status_code != 200:
            logger.warning("UW HTTP %d on %s", r.status_code, path)
            return None
        try:
            return r.json()
        except Exception:
            logger.warning("UW returned non-JSON on %s", path)
            return None

    @staticmethod
    def _unwrap_list(data: Any) -> list[dict[str, Any]]:
        """Tolerate either ``{"data": [...]}`` or a bare list payload."""
        if data is None:
            return []
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            for key in ("data", "results", "flow_alerts", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
        return []

    @staticmethod
    def _to_benzinga_shape(rec: dict[str, Any]) -> dict[str, Any]:
        """Map a UW flow record to Benzinga ``options_activity`` field names.

        Keeps the original UW payload under ``_uw_raw`` for callers that
        want richer fields (multi-leg, sector, ML flags).
        """
        # UW field names per public docs (defensive .get on all).
        ticker = rec.get("ticker") or rec.get("underlying_symbol") or rec.get("symbol")
        opt_type = rec.get("type") or rec.get("option_type")
        if isinstance(opt_type, str):
            opt_type = opt_type.upper()
        return {
            # Benzinga-compatible keys (used by dataframe renderers).
            "ticker": ticker,
            "date": rec.get("date") or rec.get("executed_at") or rec.get("created_at"),
            "time": rec.get("executed_at") or rec.get("time"),
            "sentiment": rec.get("sentiment") or rec.get("side"),
            "aggressor_ind": rec.get("aggressor_ind"),
            "option_activity_type": opt_type,  # CALL / PUT
            "option_symbol": rec.get("option_chain") or rec.get("option_symbol"),
            "underlying_price": rec.get("underlying_price") or rec.get("spot"),
            "strike_price": rec.get("strike"),
            "date_expiration": rec.get("expiry") or rec.get("expires_at"),
            "size": rec.get("size") or rec.get("volume"),
            "volume": rec.get("volume"),
            "open_interest": rec.get("open_interest") or rec.get("oi"),
            "cost_basis": rec.get("premium") or rec.get("total_premium"),
            "price": rec.get("price"),
            # UW-only signals worth surfacing in a column.
            "uw_alert_rule": rec.get("alert_rule") or rec.get("rule_name"),
            "uw_is_sweep": rec.get("is_sweep"),
            "uw_has_floor": rec.get("has_floor"),
            "uw_multileg": rec.get("is_multi_leg") or rec.get("multi_leg"),
            # Always retain the raw record for downstream consumers.
            "_uw_raw": rec,
        }

    # ── Public methods ──────────────────────────────────────

    def fetch_flow_alerts(
        self,
        tickers: str | None = None,
        *,
        limit: int = 100,
        min_premium: float | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch UW curated flow alerts (the UOA equivalent).

        Parameters
        ----------
        tickers : str | None
            Comma-separated ticker filter.  If given, the request is
            fanned out per-ticker because the bulk endpoint accepts a
            single ticker filter at a time.
        limit : int
            Max records per ticker.
        min_premium : float | None
            Optional client-side filter on UW ``total_premium``.
        """
        # Per-ticker fan-out (UW flow-alerts accepts a single ``ticker_symbol``).
        symbols: list[str | None] = (
            [s.strip().upper() for s in tickers.split(",") if s.strip()]
            if tickers
            else [None]
        )
        out: list[dict[str, Any]] = []
        for sym in symbols:
            params: dict[str, Any] = {"limit": str(limit)}
            if sym:
                params["ticker_symbol"] = sym
            data = self._get_json(UW_FLOW_ALERTS_PATH, params=params)
            recs = self._unwrap_list(data)
            for rec in recs:
                mapped = self._to_benzinga_shape(rec)
                if min_premium is not None:
                    try:
                        if float(mapped.get("cost_basis") or 0) < min_premium:
                            continue
                    except (TypeError, ValueError):
                        pass
                out.append(mapped)
        return out


# ── Module-level helpers (mirrors ingest_benzinga_financial.py shape) ──


def fetch_uw_options_flow(
    api_key: str,
    tickers: str,
    *,
    limit: int = 100,
    min_premium: float | None = None,
) -> list[dict[str, Any]]:
    """Standalone wrapper for one-shot UW flow-alerts fetches.

    Returns ``[]`` on any error; never raises.
    """
    if not api_key:
        return []
    try:
        adapter = UnusualWhalesAdapter(api_key)
    except RuntimeError:
        return []
    try:
        return adapter.fetch_flow_alerts(
            tickers, limit=limit, min_premium=min_premium,
        )
    except Exception:
        logger.warning("fetch_uw_options_flow failed", exc_info=True)
        return []
    finally:
        adapter.close()


def is_uw_configured() -> bool:
    """Return True if a UW key is present in the environment."""
    return bool(os.getenv("UNUSUAL_WHALES_API_KEY", "").strip())
