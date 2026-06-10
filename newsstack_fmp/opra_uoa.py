"""Unusual Options Activity (UOA) detector backed by Databento OPRA.PILLAR.

This module replaces the third-party Unusual Whales `/option-trades/flow-alerts`
endpoint with a self-hosted detector that consumes the raw OPRA.PILLAR trade
feed from Databento. After the 2026-05-12 provider audit, the user activated
Databento `OPRA.PILLAR` and cancelled the Unusual Whales subscription; the
remaining task was to relocate the UOA logic in-process so existing monitor
consumers keep working.

Design contract
---------------
- **Input**: a pandas DataFrame of OPRA `trades` records (one row per print)
  plus a parallel DataFrame of `definition` records (one row per instrument
  per session) used to map ``instrument_id`` -> (underlying ticker, strike,
  expiration, call/put). The caller is responsible for pulling these from
  Databento via the existing ``databento_provider`` abstraction so this
  module stays I/O-free and unit-testable without a network.
- **Output**: a list of dicts shaped to match the Benzinga
  ``options_activity`` field set already produced by
  ``newsstack_fmp.ingest_unusual_whales.UnusualWhalesAdapter._to_benzinga_shape``,
  so downstream renderers in ``open_prep/streamlit_monitor.py`` need zero
  changes.

Detection heuristics
--------------------
The Unusual Whales "flow-alerts" feed combines several signals; this module
implements the documented, replicable ones:

1. **Sweep detection** — multiple prints at the same OCC OSI symbol within a
   sub-second window across different exchanges. OPRA tags each trade with a
   ``publisher_id``/``exchange`` field; >=3 exchange touches inside a 500 ms
   bucket marks the cluster as a sweep.
2. **Aggressor classification** — OPRA `trades` carries the ``side`` field
   (`A` = ask-side / aggressive buy, `B` = bid-side / aggressive sell,
   `N` = neutral / cross). We pass this through into
   ``aggressor_ind`` and ``sentiment``.
3. **Block-trade premium gate** — total notional premium
   ``size * price * 100`` (OCC contract multiplier) above a configurable
   minimum (default $25k) qualifies the trade for the UOA feed. The same
   `min_premium` kwarg semantics as the UW adapter are preserved.
4. **Multi-leg flag** — if a sweep cluster contains both a call and a put
   leg on the same underlying within the same window we mark
   ``uw_multileg=True`` for compatibility.

The full raw OPRA record is preserved under ``_opra_raw`` mirroring the UW
``_uw_raw`` convention. The presence of ``_opra_raw`` instead of ``_uw_raw``
is the only schema difference renderers will observe; the
``streamlit_monitor`` drop-column logic must be extended in lockstep (see
PR description for the matching shim).

This module is intentionally split from the ingestion wrapper
(``newsstack_fmp/ingest_opra_options_flow.py``) so that:

- The detector can be unit-tested with synthetic DataFrames without any
  Databento HTTP dependency.
- The ingestion wrapper can swap in different timeseries backends (e.g. live
  WebSocket vs historical ``get_range``) without touching detector logic.

Refs:
  - Databento OPRA.PILLAR symbology: parent symbology supported as ``TICKER.OPT``
  - Audit follow-up: ``_invest/all-providers-audit-2026-05-12.md`` row 4
  - Replaces: ``newsstack_fmp/ingest_unusual_whales.py`` flow-alerts path
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

# OCC contract multiplier — every equity option represents 100 shares of the
# underlying. Notional premium = size * price * 100. This is invariant across
# all OPRA-listed instruments; if a non-standard contract size ever appears
# (mini-options, 1099 ETF flexes) the definition record carries the actual
# ``contract_size`` field which callers can override via ``contract_size_for``.
_OCC_CONTRACT_MULTIPLIER = 100

# Default sweep window: 500 ms is the conventional retail-UOA bucket because
# that's roughly the round-trip latency from a single broker to the four
# largest OPRA exchanges. Configurable via ``sweep_window_ms`` kwarg.
_DEFAULT_SWEEP_WINDOW_MS = 500

# Minimum number of distinct exchange touches inside the sweep window to
# qualify a cluster as a sweep. UW's public docs cite "3+ exchanges" so we
# match that floor. Configurable via ``sweep_min_exchanges`` kwarg.
_DEFAULT_SWEEP_MIN_EXCHANGES = 3

# Default premium gate: $25k notional. Aligned with UW's "minimum" tier
# threshold so the volume of records returned per ticker stays in the same
# order of magnitude as the previous adapter — downstream renderers do their
# own pagination/sorting and we don't want to flood the dataframe.
_DEFAULT_MIN_PREMIUM = 25_000.0


@dataclass(frozen=True)
class OpraDefinitionRecord:
    """Minimal projection of an OPRA ``definition`` row needed for UOA.

    The full definition schema has ~40 columns; we only project the four
    used by the detector. Callers that already have a DataFrame can build
    these via ``OpraDefinitionRecord.from_row(...)``.
    """

    instrument_id: int
    underlying: str
    strike: float
    expiration: str  # ISO-8601 date, e.g. "2026-06-21"
    option_type: str  # "CALL" or "PUT"
    raw_symbol: str | None = None  # OCC OSI symbol (optional; pass-through)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "OpraDefinitionRecord":
        opt_type_raw = str(row.get("instrument_class") or row.get("option_type") or "").upper()
        # OPRA definition uses 'C' / 'P' in instrument_class for options.
        if opt_type_raw in ("C", "CALL"):
            opt_type = "CALL"
        elif opt_type_raw in ("P", "PUT"):
            opt_type = "PUT"
        else:
            opt_type = ""
        return cls(
            instrument_id=int(row["instrument_id"]),
            underlying=str(row.get("underlying") or row.get("asset") or "").upper().strip(),
            strike=float(row.get("strike_price") or row.get("strike") or 0.0),
            expiration=str(row.get("expiration") or row.get("expiry") or ""),
            option_type=opt_type,
            raw_symbol=str(row.get("raw_symbol") or row.get("symbol") or "") or None,
        )


def _side_to_aggressor(side: str | None) -> tuple[str, str]:
    """Map OPRA ``side`` field to (aggressor_ind, sentiment) strings.

    OPRA codes per Databento docs:
      'A' = trade hit the ask (aggressive buyer)
      'B' = trade hit the bid (aggressive seller)
      'N' = no aggressor classification available (cross / unknown)

    The Benzinga-compatible field set uses ``aggressor_ind`` as a free-text
    label ('A'/'B'/'N') and ``sentiment`` as 'BULLISH'/'BEARISH'/'NEUTRAL'.
    """
    s = (side or "").strip().upper()
    if s == "A":
        return "A", "BULLISH"
    if s == "B":
        return "B", "BEARISH"
    return "N", "NEUTRAL"


def _premium_of(row: Mapping[str, Any], contract_size: int = _OCC_CONTRACT_MULTIPLIER) -> float:
    """Notional premium for one OPRA trade = price * size * contract_size.

    OPRA ``price`` is the per-contract premium in dollars; ``size`` is the
    number of contracts. Returns ``0.0`` on any missing/invalid field — the
    caller's premium gate will then filter these out.

    Only ``size`` is consulted. The Databento OPRA ``trades`` schema never
    carries ``volume`` (that belongs to OHLCV aggregates); a former
    ``or row.get("volume")`` fallback could silently substitute a cumulative
    session total for a single print, inflating premium by orders of
    magnitude (audit #2670 W1).
    """
    try:
        _price_raw = row.get("price")
        _size_raw = row.get("size")
        price = float(_price_raw if _price_raw is not None else 0.0)
        size = float(_size_raw if _size_raw is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0
    if price <= 0.0 or size <= 0.0:
        return 0.0
    return price * size * float(contract_size)


def _normalize_ts(value: Any) -> int:
    """Return the trade timestamp as nanoseconds since UNIX epoch.

    OPRA via Databento ships ``ts_event`` as int64 ns. We tolerate
    ``datetime`` / ``pd.Timestamp`` / int / float for unit-test convenience.
    """
    if value is None:
        return 0
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if hasattr(value, "value"):  # pd.Timestamp
        try:
            return int(value.value)
        except Exception:
            pass
    if isinstance(value, datetime):
        return int(value.replace(tzinfo=value.tzinfo or UTC).timestamp() * 1_000_000_000)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ts_to_iso(ns: int) -> str:
    """Render a ns-since-epoch timestamp as ISO-8601 UTC, second-resolution."""
    if ns <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return ""


def detect_unusual_options_activity(
    trades: Iterable[Mapping[str, Any]],
    definitions: Iterable[OpraDefinitionRecord | Mapping[str, Any]],
    *,
    min_premium: float | None = None,
    sweep_window_ms: int = _DEFAULT_SWEEP_WINDOW_MS,
    sweep_min_exchanges: int = _DEFAULT_SWEEP_MIN_EXCHANGES,
    contract_size: int = _OCC_CONTRACT_MULTIPLIER,
    tickers: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Detect UOA records from OPRA trades + definition rows.

    Parameters
    ----------
    trades
        Iterable of dict-like rows from OPRA ``trades`` schema. Must carry at
        minimum: ``instrument_id``, ``ts_event``, ``price``, ``size``,
        ``side``. May optionally carry ``publisher_id`` / ``exchange`` for
        sweep detection.
    definitions
        Iterable of ``OpraDefinitionRecord`` or dict-like rows from OPRA
        ``definition`` schema. Used to map ``instrument_id`` to underlying,
        strike, expiration, call/put.
    min_premium
        Optional notional-premium gate in USD. Trades with computed premium
        below this threshold are filtered out before sweep detection. When
        ``None``, defaults to ``_DEFAULT_MIN_PREMIUM`` (= $25k).
    sweep_window_ms
        Time-bucket size for sweep clustering. Default 500 ms.
    sweep_min_exchanges
        Minimum distinct ``publisher_id`` values inside a bucket to flag the
        cluster as a sweep. Default 3.
    contract_size
        OCC contract multiplier. Default 100. Override per-instrument via
        the ``definition.contract_size`` field if non-standard.
    tickers
        Optional whitelist of underlying tickers to keep. If provided, any
        trade resolving to an underlying outside this set is dropped before
        further processing. Matches the per-ticker filter shape of the UW
        adapter's ``fetch_flow_alerts(tickers=...)`` API.

    Returns
    -------
    list[dict[str, Any]]
        UOA records shaped identically to the Benzinga-compatible payload
        produced by ``UnusualWhalesAdapter._to_benzinga_shape``. Each row
        carries the original OPRA trade under ``_opra_raw``.
    """

    gate = float(_DEFAULT_MIN_PREMIUM if min_premium is None else min_premium)
    window_ns = max(int(sweep_window_ms), 1) * 1_000_000
    min_exchanges = max(int(sweep_min_exchanges), 1)
    ticker_filter: set[str] | None = (
        {str(t).upper().strip() for t in tickers if str(t).strip()} if tickers else None
    )

    # Build the instrument_id -> definition projection map first. This is a
    # tight loop on the typical OPRA per-session universe (~1M instruments)
    # but each lookup later is O(1). We tolerate both pre-built records and
    # raw row dicts so callers don't have to materialize OpraDefinitionRecord
    # unless they want to.
    def_map: dict[int, OpraDefinitionRecord] = {}
    for d in definitions:
        rec = d if isinstance(d, OpraDefinitionRecord) else OpraDefinitionRecord.from_row(d)
        def_map[rec.instrument_id] = rec

    # Filter trades to the ticker whitelist + premium gate while bucketing
    # by (instrument_id, sweep-window-bucket) for sweep detection. We use a
    # dict-of-list rather than pandas groupby to avoid forcing pandas as a
    # hard dependency for this module.
    buckets: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    bucket_exchanges: dict[tuple[int, int], set[Any]] = defaultdict(set)
    bucket_definitions: dict[tuple[int, int], OpraDefinitionRecord | None] = {}

    for row in trades:
        try:
            inst = int(row.get("instrument_id") or 0)
        except (TypeError, ValueError):
            continue
        if inst <= 0:
            continue
        defn = def_map.get(inst)
        if defn is None:
            # Unknown instrument — skip rather than emit malformed records.
            # This is the expected behaviour when the caller forgets to fetch
            # the parallel definition slice for the same session.
            continue
        if ticker_filter is not None and defn.underlying not in ticker_filter:
            continue
        premium = _premium_of(row, contract_size=contract_size)
        if premium < gate:
            continue
        # ts_event (exchange matching-engine time) is preferred; ts_recv
        # (Databento receive time, includes network latency) is a disclosed
        # proxy. The chosen source is stashed so consumers can tell which
        # clock drove sweep-window clustering (audit #2670 W5).
        _ts_event_raw = row.get("ts_event")
        if _ts_event_raw is not None:
            ts_ns = _normalize_ts(_ts_event_raw)
            ts_source = "ts_event"
        else:
            ts_ns = _normalize_ts(row.get("ts_recv"))
            ts_source = "ts_recv"
        bucket_key = (inst, ts_ns // window_ns if ts_ns > 0 else 0)
        # Stash the augmented row (we'll need premium, ts_ns, side later).
        enriched = dict(row)
        enriched["_premium_usd"] = premium
        enriched["_ts_ns"] = ts_ns
        enriched["_ts_source"] = ts_source
        buckets[bucket_key].append(enriched)
        exch = row.get("publisher_id") or row.get("exchange")
        if exch is not None:
            bucket_exchanges[bucket_key].add(exch)
        bucket_definitions[bucket_key] = defn

    # Materialize sweep / non-sweep records. We emit ONE record per trade row
    # (matching UW's per-print granularity) but enrich each with the cluster
    # context so downstream consumers can group on (ticker, ts_event) if they
    # want a sweep-level view. The ``uw_is_sweep`` flag is True iff the
    # bucket has >= sweep_min_exchanges distinct publisher_ids.
    #
    # We also detect cross-leg activity: if both a CALL and a PUT for the
    # same underlying fire inside overlapping time windows we set
    # ``uw_multileg`` on each row. This is a same-underlying join across
    # buckets keyed by (underlying, window_bucket) — handled in a second
    # pass below so the per-instrument bucket loop above stays O(N).
    multileg_keys: dict[tuple[str, int], set[str]] = defaultdict(set)
    for (inst, bucket_idx), defn in bucket_definitions.items():
        if defn is None or not defn.option_type:
            continue
        multileg_keys[(defn.underlying, bucket_idx)].add(defn.option_type)

    out: list[dict[str, Any]] = []
    for (inst, bucket_idx), rows in buckets.items():
        defn = bucket_definitions[(inst, bucket_idx)]
        if defn is None:
            continue
        is_sweep = len(bucket_exchanges[(inst, bucket_idx)]) >= min_exchanges
        is_multileg = len(multileg_keys.get((defn.underlying, bucket_idx), set())) > 1
        for row in rows:
            aggressor, sentiment = _side_to_aggressor(row.get("side"))
            ts_iso = _ts_to_iso(int(row.get("_ts_ns") or 0))
            out.append(
                {
                    # Benzinga-compatible keys (must mirror the UW adapter's
                    # _to_benzinga_shape output exactly).
                    "ticker": defn.underlying,
                    "date": ts_iso[:10] if ts_iso else "",
                    "time": ts_iso,
                    # Which OPRA clock produced "time": "ts_event"
                    # (exchange) or "ts_recv" (receive-time proxy) —
                    # audit #2670 W5.
                    "ts_source": row.get("_ts_source"),
                    "sentiment": sentiment,
                    "aggressor_ind": aggressor,
                    "option_activity_type": defn.option_type,
                    "option_symbol": defn.raw_symbol,
                    "underlying_price": None,  # Not present in OPRA trades; nbbo schema would be needed
                    "strike_price": defn.strike,
                    "date_expiration": defn.expiration,
                    # OPRA trades carry per-print ``size`` only; ``volume``
                    # (cumulative session total) is not in this schema. Do
                    # NOT cross-fill one from the other — a single print is
                    # not a session total (audit #2670 W1).
                    "size": row.get("size"),
                    "volume": row.get("volume"),
                    "open_interest": None,  # Not present in OPRA trades stream
                    "cost_basis": row.get("_premium_usd"),
                    "price": row.get("price"),
                    # UW-compat signal columns. The two we can compute from
                    # OPRA alone are sweep + multileg. ``uw_alert_rule``
                    # carries the rule that fired so renderers can tag the
                    # row visually; ``uw_has_floor`` is a UW-proprietary
                    # signal that we cannot compute from OPRA (no
                    # exchange-classifies-as-floor field) — set to None.
                    "uw_alert_rule": (
                        "opra_sweep" if is_sweep else "opra_block"
                    ),
                    "uw_is_sweep": is_sweep,
                    "uw_has_floor": None,
                    "uw_multileg": is_multileg,
                    # Source-tag so renderers/aggregators can tell OPRA-
                    # derived rows from UW-derived rows during the
                    # transition period.
                    "_source": "databento_opra",
                    "_opra_raw": {
                        k: v for k, v in row.items()
                        if not k.startswith("_")
                    },
                }
            )

    # Sort newest-first so the default table view matches UW's reverse-
    # chronological convention. Ties broken by premium desc (larger blocks
    # first inside the same bucket).
    out.sort(key=lambda r: (r.get("time") or "", r.get("cost_basis") or 0.0), reverse=True)
    return out


__all__ = [
    "OpraDefinitionRecord",
    "detect_unusual_options_activity",
]
