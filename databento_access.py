"""Truthful Databento catalog, historical-range, and live-access probes."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetAccessStatus:
    dataset: str
    catalog_present: bool
    historical_range_available: bool | None
    historical_start: str | None
    historical_end: str | None
    live_checked: bool
    live_entitled: bool | None
    reason: str


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    for method in (getattr(value, "model_dump", None), getattr(value, "to_dict", None)):
        if callable(method):
            converted = method()
            if isinstance(converted, Mapping):
                return converted
    return None


def list_catalog_datasets_from_client(client: Any) -> list[str]:
    """Return Databento's global dataset catalog, not account entitlements."""
    raw = client.metadata.list_datasets()
    return sorted({str(item).strip().upper() for item in raw if str(item).strip()})


def inspect_historical_access(
    client: Any,
    dataset: str,
    *,
    catalog_datasets: list[str] | None = None,
) -> DatasetAccessStatus:
    """Inspect catalog membership and historical range for one dataset."""
    normalized = str(dataset).strip().upper()
    catalog = {
        str(item).strip().upper()
        for item in (
            catalog_datasets
            if catalog_datasets is not None
            else list_catalog_datasets_from_client(client)
        )
        if str(item).strip()
    }
    catalog_present = normalized in catalog
    try:
        raw_range = client.metadata.get_dataset_range(dataset=normalized)
    except Exception as exc:
        from databento_utils import _redact_sensitive_error_text

        message = _redact_sensitive_error_text(str(exc)).lower()
        if any(marker in message for marker in ("license", "not entitled", "unauthorized", "forbidden")):
            available: bool | None = False
            category = "license_or_auth_denied"
        elif any(marker in message for marker in ("429", "rate limit", "too many requests")):
            available = None
            category = "rate_limited"
        elif any(marker in message for marker in ("timeout", "network", "connection", "dns")):
            available = None
            category = "network_error"
        else:
            available = None
            category = "unknown_error"
        return DatasetAccessStatus(
            dataset=normalized,
            catalog_present=catalog_present,
            historical_range_available=available,
            historical_start=None,
            historical_end=None,
            live_checked=False,
            live_entitled=None,
            reason=f"historical_range_{category}:{type(exc).__name__}",
        )
    range_map = _as_mapping(raw_range)
    if range_map is None:
        return DatasetAccessStatus(
            dataset=normalized,
            catalog_present=catalog_present,
            historical_range_available=None,
            historical_start=None,
            historical_end=None,
            live_checked=False,
            live_entitled=None,
            reason="historical_range_unparseable",
        )
    start = str(range_map.get("start") or "").strip() or None
    end = str(range_map.get("end") or "").strip() or None
    available = bool(start or end)
    return DatasetAccessStatus(
        dataset=normalized,
        catalog_present=catalog_present,
        historical_range_available=available,
        historical_start=start,
        historical_end=end,
        live_checked=False,
        live_entitled=None,
        reason="historical_range_available" if available else "historical_range_empty",
    )


def probe_live_access(
    status: DatasetAccessStatus,
    *,
    api_key: str,
    schema: str,
    symbol: str,
    timeout_seconds: float = 5.0,
) -> DatasetAccessStatus:
    """Explicitly attempt one bounded live subscription.

    A timeout without any record is reported as unknown because a closed market
    cannot prove or disprove entitlement.  License/auth failures are reported as
    ``False``; receiving any record proves live access for the requested tuple.
    """
    result: dict[str, Any] = {}
    client_box: dict[str, Any] = {}

    def _run() -> None:
        try:
            from databento_client import _import_databento

            db = _import_databento()
            client = db.Live(key=api_key)
            client_box["client"] = client
            client.subscribe(
                dataset=status.dataset,
                schema=str(schema).strip().lower(),
                symbols=[str(symbol).strip()],
                stype_in="parent" if str(symbol).upper().endswith(".OPT") else "raw_symbol",
            )
            for _record in client:
                result["entitled"] = True
                result["reason"] = "live_record_received"
                break
        except Exception as exc:
            from databento_utils import _redact_sensitive_error_text

            text = _redact_sensitive_error_text(str(exc)).lower()
            denied = any(
                marker in text
                for marker in ("license_not_found", "not entitled", "unauthorized", "invalid api key")
            )
            result["entitled"] = False if denied else None
            result["reason"] = "live_access_denied" if denied else f"live_probe_error:{type(exc).__name__}"
        finally:
            client = client_box.get("client")
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    logger.debug("Databento live probe cleanup failed", exc_info=True)

    thread = threading.Thread(target=_run, name="databento-live-access-probe", daemon=True)
    thread.start()
    thread.join(max(float(timeout_seconds), 0.1))
    if thread.is_alive():
        client = client_box.get("client")
        if client is not None:
            try:
                client.stop()
            except Exception:
                logger.debug("Databento timed-out live probe cleanup failed", exc_info=True)
        thread.join(1.0)
        return replace(
            status,
            live_checked=True,
            live_entitled=None,
            reason="live_probe_timeout_no_record",
        )
    return replace(
        status,
        live_checked=True,
        live_entitled=result.get("entitled"),
        reason=str(result.get("reason") or "live_probe_no_result"),
    )
