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
import threading
from typing import Any

import httpx

from newsstack_fmp._bz_http import _request_with_status_retry

logger = logging.getLogger(__name__)

# Base URL for all UW REST endpoints.
UW_BASE_URL = "https://api.unusualwhales.com/api"

# Endpoint paths (kept as constants for grep/refactor).
UW_FLOW_ALERTS_PATH = "/option-trades/flow-alerts"
UW_FLOW_RECENT_PATH = "/stock/{ticker}/flow-recent"
# v3 P-4b: dark-pool prints + dealer-gamma-by-strike
UW_DARKPOOL_TICKER_PATH = "/darkpool/{ticker}"
UW_DARKPOOL_RECENT_PATH = "/darkpool/recent"
UW_SPOT_GEX_STRIKE_PATH = "/stock/{ticker}/spot-exposures/strike"
# v3 P-4d: marketwide call/put-premium tide
UW_MARKET_TIDE_PATH = "/market/market-tide"
# v3 P-4c: bulk Form-4 insider transactions (single source for monitor + ML)
UW_INSIDER_TX_PATH = "/insider/transactions"
# B1 (PR2 2026-05-09): broad-market news headlines, default-OFF in pipeline.
UW_NEWS_HEADLINES_PATH = "/news/headlines"


# ── Once-per-endpoint suppression (mirrors _bz_http.py) ──────────────
# When UW returns a permanent failure (auth/tier/missing), we mark the
# endpoint disabled for the rest of the process so subsequent polls
# short-circuit without burning quota or filling logs.  Per-process
# state (cleared on restart); idempotent helpers exposed for tests.
_DISABLED_ENDPOINTS: set[str] = set()
_disabled_lock = threading.Lock()


# Audit-fix (2026-05-09): UnusualWhalesEndpointDisabledError class removed.
# It was defined but never raised — the actual mute mechanism is the
# is_uw_endpoint_disabled()/mark_uw_endpoint_disabled() pair plus a
# generic-Exception catch in the pipeline. Reintroduce only if a caller
# is wired to handle it specifically.


def is_uw_endpoint_disabled(label: str) -> bool:
    with _disabled_lock:
        return label in _DISABLED_ENDPOINTS


def mark_uw_endpoint_disabled(label: str) -> None:
    with _disabled_lock:
        _DISABLED_ENDPOINTS.add(label)


def clear_uw_disabled_endpoints() -> None:
    with _disabled_lock:
        _DISABLED_ENDPOINTS.clear()


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
                # v3 P-4a: UW marks UW-CLIENT-API-ID as a mandatory header
                # in their public skill.md manifest. Currently tolerated as
                # missing, but UW may begin enforcing this; setting it now
                # avoids a future surprise 4xx.
                "UW-CLIENT-API-ID": "100001",
            },
        )

    def close(self) -> None:
        self.client.close()

    # ── Internal ────────────────────────────────────────────

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        # B2: Skip the network call if a previous response marked this
        # endpoint as permanently unavailable (tier-limit, missing entitlement).
        if is_uw_endpoint_disabled(path):
            return None
        url = f"{UW_BASE_URL}{path}"
        # Audit-fix (2026-05-10, F2): use the shared retry primitive from
        # _bz_http so 429/5xx and transient network errors are retried with
        # backoff + Retry-After honoring. The primitive returns a Response
        # without raise_for_status so non-retryable 4xx (401/403/404) still
        # flow into the existing mark_uw_endpoint_disabled paths below.
        # 429 either succeeds on retry or raises HTTPStatusError on retry
        # exhaustion (caught here) -- the legacy 429 fall-through branch
        # below is therefore unreachable and was removed.
        try:
            r = _request_with_status_retry(self.client, url, params or {})
        except httpx.HTTPStatusError as exc:
            # Raised after retry exhaustion on a 429/5xx response.
            code = exc.response.status_code
            if code == 429:
                logger.warning(
                    "UW rate-limited (429) on %s after retries", path
                )
            else:
                logger.warning(
                    "UW HTTP %d on %s after retries", code, path
                )
            return None
        except httpx.HTTPError as exc:
            logger.warning("UW HTTP error on %s: %s", path, exc)
            return None
        if r.status_code == 401:
            logger.error("UW auth failed (401) — check UNUSUAL_WHALES_API_KEY")
            mark_uw_endpoint_disabled(path)
            return None
        if r.status_code == 403:
            logger.warning("UW 403 on %s — endpoint not in current plan tier", path)
            mark_uw_endpoint_disabled(path)
            return None
        if r.status_code == 404:
            logger.warning("UW 404 on %s — endpoint not available", path)
            mark_uw_endpoint_disabled(path)
            return None
        if r.status_code != 200:
            logger.warning("UW HTTP %d on %s", r.status_code, path)
            return None
        try:
            return r.json()
        except Exception:
            # Quantum-sweep L6: include a 200-char body sample so silent
            # UW schema changes (HTML maintenance pages, plain-text error
            # blobs, gateway responses) are diagnosable from logs without
            # round-tripping through curl.
            logger.warning(
                "UW returned non-JSON on %s (body sample=%r)",
                path,
                r.text[:200],
            )
            return None

    @staticmethod
    def _unwrap_list(data: Any) -> list[dict[str, Any]]:
        """Tolerate either ``{"data": [...]}`` or a bare list payload.

        Audit-fix (2026-05-10, F4): emit warnings when records are dropped
        from a list/wrapper or when no recognized wrapper key is found, so
        silent UW schema drift becomes visible in CI artifacts. The set of
        wrapper keys is intentionally unchanged \u2014 do not add speculative
        keys (e.g. ``records``) without UW endpoint evidence.
        """
        if data is None:
            return []
        if isinstance(data, list):
            kept = [r for r in data if isinstance(r, dict)]
            dropped = len(data) - len(kept)
            if dropped:
                logger.warning(
                    "UW _unwrap_list: dropped %d non-dict item(s) from bare list "
                    "(possible schema drift; example type=%s)",
                    dropped,
                    type(next((x for x in data if not isinstance(x, dict)), None)).__name__,
                )
            return kept
        if isinstance(data, dict):
            for key in ("data", "results", "flow_alerts", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    kept = [r for r in v if isinstance(r, dict)]
                    dropped = len(v) - len(kept)
                    if dropped:
                        logger.warning(
                            "UW _unwrap_list: dropped %d non-dict item(s) from "
                            "wrapper key %r (possible schema drift)",
                            dropped,
                            key,
                        )
                    return kept
            logger.warning(
                "UW _unwrap_list: no recognized wrapper key in dict payload "
                "(possible schema drift; keys=%r)",
                sorted(data.keys()),
            )
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

    # ── v3 P-4b: dark-pool prints + dealer-gamma-by-strike ──

    def fetch_darkpool(
        self, ticker: str, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch dark-pool prints for a single ticker."""
        sym = (ticker or "").strip().upper()
        if not sym:
            return []
        data = self._get_json(
            UW_DARKPOOL_TICKER_PATH.format(ticker=sym),
            params={"limit": str(limit)},
        )
        return self._unwrap_list(data)

    def fetch_darkpool_recent(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch the firehose of recent dark-pool prints across all tickers."""
        data = self._get_json(
            UW_DARKPOOL_RECENT_PATH, params={"limit": str(limit)},
        )
        return self._unwrap_list(data)

    def fetch_spot_gex(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch dealer-gamma exposure broken down by strike.

        Returns a list of per-strike records with full Greek surface
        (gamma/delta/charm/vanna for both calls + puts, broken down by
        OI/volume/bid/ask). All numeric values are returned as strings.
        """
        sym = (ticker or "").strip().upper()
        if not sym:
            return []
        data = self._get_json(UW_SPOT_GEX_STRIKE_PATH.format(ticker=sym))
        return self._unwrap_list(data)

    # ── v3 P-4d: marketwide tide ──

    def fetch_market_tide(self) -> list[dict[str, Any]]:
        """Fetch the intraday net-call/put-premium tide timeseries.

        Returns ~80 5-minute records for the current trading day.
        The last record is the session-to-date snapshot.
        """
        data = self._get_json(UW_MARKET_TIDE_PATH)
        return self._unwrap_list(data)

    # ── v3 P-4c: bulk Form-4 insider transactions ──

    def fetch_insider_transactions(
        self, *, limit: int = 100, ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch Form-4 insider transactions (bulk or per-ticker).

        Each record is one Form-4 line item — drop-in compatible with the
        FMP per-symbol shape mapped earlier in P-3c.
        """
        params: dict[str, Any] = {"limit": str(limit)}
        sym = (ticker or "").strip().upper()
        if sym:
            params["ticker_symbol"] = sym
        data = self._get_json(UW_INSIDER_TX_PATH, params=params)
        return self._unwrap_list(data)

    # ── B1 (PR2 2026-05-09): broad-market news headlines ──

    def fetch_news_headlines(
        self,
        *,
        limit: int = 100,
        ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch UW broad-market news headlines.

        Endpoint: ``/news/headlines`` (default-OFF in pipeline; enable
        via ``ENABLE_UW_NEWS=1``).  Marked DISABLED on first 401/403/404
        so subsequent polls short-circuit without burning quota.
        """
        params: dict[str, Any] = {"limit": str(limit)}
        sym = (ticker or "").strip().upper()
        if sym:
            params["ticker_symbol"] = sym
        data = self._get_json(UW_NEWS_HEADLINES_PATH, params=params)
        return self._unwrap_list(data)


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


# ── v3 P-4b/d: module-level wrappers for new endpoints ──


def _adapter_or_none(api_key: str) -> UnusualWhalesAdapter | None:
    if not api_key:
        return None
    try:
        return UnusualWhalesAdapter(api_key)
    except RuntimeError:
        return None


def fetch_uw_darkpool(
    api_key: str, ticker: str, *, limit: int = 100,
) -> list[dict[str, Any]]:
    """Standalone wrapper for dark-pool prints. Returns ``[]`` on any error."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_darkpool(ticker, limit=limit)
    except Exception:
        logger.warning("fetch_uw_darkpool failed", exc_info=True)
        return []
    finally:
        adapter.close()


def fetch_uw_darkpool_recent(
    api_key: str, *, limit: int = 100,
) -> list[dict[str, Any]]:
    """Standalone wrapper for the recent-prints firehose."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_darkpool_recent(limit=limit)
    except Exception:
        logger.warning("fetch_uw_darkpool_recent failed", exc_info=True)
        return []
    finally:
        adapter.close()


def fetch_uw_spot_gex(api_key: str, ticker: str) -> list[dict[str, Any]]:
    """Standalone wrapper for dealer-gamma-by-strike."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_spot_gex(ticker)
    except Exception:
        logger.warning("fetch_uw_spot_gex failed", exc_info=True)
        return []
    finally:
        adapter.close()


def fetch_uw_market_tide(api_key: str) -> list[dict[str, Any]]:
    """Standalone wrapper for marketwide call/put-premium tide."""
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_market_tide()
    except Exception:
        logger.warning("fetch_uw_market_tide failed", exc_info=True)
        return []
    finally:
        adapter.close()


def fetch_uw_insider_transactions(
    api_key: str, *, limit: int = 100, ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Standalone wrapper for UW Form-4 insider transactions (v3 P-4c).

    Supports either bulk-mode (no ticker) or per-symbol filtering.
    Returns ``[]`` on any error; never raises.
    """
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_insider_transactions(limit=limit, ticker=ticker)
    except Exception:
        logger.warning("fetch_uw_insider_transactions failed", exc_info=True)
        return []
    finally:
        adapter.close()


def fetch_uw_news_headlines(
    api_key: str,
    *,
    limit: int = 100,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Standalone wrapper for UW /news/headlines (B1, PR2 2026-05-09).

    Returns ``[]`` on missing key, disabled endpoint, or any error.
    """
    adapter = _adapter_or_none(api_key)
    if adapter is None:
        return []
    try:
        return adapter.fetch_news_headlines(limit=limit, ticker=ticker)
    except Exception:
        logger.warning("fetch_uw_news_headlines failed", exc_info=True)
        return []
    finally:
        adapter.close()
