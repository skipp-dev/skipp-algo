"""Per-symbol trades microstructure aggregator (WP-I).

Aggregates a Databento ``trades`` stream into the two raw microstructure
signals consumed downstream by :mod:`scripts.smc_flow_qualifier`:

* ``buy_volume_pct`` -- share of aggressive-buy volume in ``[0, 100]``.
* ``avg_trade_size`` -- mean executed size per trade.

The aggregation (:func:`aggregate_trades_microstructure`) is a pure,
deterministic function that operates on an in-memory ``trades`` table (a
``pandas.DataFrame`` with ``size`` / ``side`` columns, or any iterable of
record-like objects exposing ``.size`` and ``.side``). It performs **no**
network I/O so it can be unit-tested with synthetic fixtures.

The live fetch helpers (:func:`fetch_symbol_trades`,
:func:`fetch_symbol_microstructure`) are thin wrappers around the shared
Databento range-fetch plumbing in :mod:`databento_client`; they are not
unit-tested (they require entitlements and hit the network).

Side convention (Databento ``TradeMsg.side``): ``"A"`` = aggressive buy
(lifts the ask), ``"B"`` = aggressive sell (hits the bid), ``"N"`` / anything
else = no aggressor. Neutral trades are excluded from the buy/sell split but
still counted in ``total_size`` / ``n_trades`` so ``avg_trade_size`` reflects
the full tape. When there is no directional volume the buy share defaults to
``50.0`` -- the same neutral value :mod:`scripts.smc_flow_qualifier` assumes
when the column is absent -- so a flat tape never fabricates a directional
bias for the overlay.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd


_BUY_SIDE = "A"
_SELL_SIDE = "B"
_NEUTRAL_BUY_PCT = 50.0

# Keys returned by :func:`aggregate_trades_microstructure`. Kept explicit so
# callers (and tests) can assert the contract without importing pandas.
MICROSTRUCTURE_KEYS = (
    "buy_volume_pct",
    "avg_trade_size",
    "total_size",
    "n_trades",
    "buy_size",
    "sell_size",
)


def _empty_result() -> dict[str, Any]:
    return {
        "buy_volume_pct": _NEUTRAL_BUY_PCT,
        "avg_trade_size": 0.0,
        "total_size": 0,
        "n_trades": 0,
        "buy_size": 0,
        "sell_size": 0,
    }


def _finalize(
    *, n_trades: int, total_size: int, buy_size: int, sell_size: int
) -> dict[str, Any]:
    directional = buy_size + sell_size
    buy_pct = (buy_size / directional * 100.0) if directional > 0 else _NEUTRAL_BUY_PCT
    avg_size = (total_size / n_trades) if n_trades > 0 else 0.0
    return {
        "buy_volume_pct": round(float(buy_pct), 4),
        "avg_trade_size": round(float(avg_size), 6),
        "total_size": int(total_size),
        "n_trades": int(n_trades),
        "buy_size": int(buy_size),
        "sell_size": int(sell_size),
    }


def _aggregate_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    if "size" not in df.columns or len(df) == 0:
        return _empty_result()

    sizes = df["size"].fillna(0)
    n_trades = len(df)
    total_size = int(sizes.sum())

    if "side" in df.columns:
        side = df["side"].astype("string").fillna("")
        buy_size = int(sizes[side == _BUY_SIDE].sum())
        sell_size = int(sizes[side == _SELL_SIDE].sum())
    else:
        buy_size = 0
        sell_size = 0

    return _finalize(
        n_trades=n_trades,
        total_size=total_size,
        buy_size=buy_size,
        sell_size=sell_size,
    )


def _aggregate_iterable(records: Iterable[Any]) -> dict[str, Any]:
    n_trades = 0
    total_size = 0
    buy_size = 0
    sell_size = 0

    for rec in records:
        try:
            size = int(rec.size)
        except (AttributeError, TypeError, ValueError):
            continue
        side = getattr(rec, "side", None)
        n_trades += 1
        total_size += size
        if side == _BUY_SIDE:
            buy_size += size
        elif side == _SELL_SIDE:
            sell_size += size

    if n_trades == 0:
        return _empty_result()

    return _finalize(
        n_trades=n_trades,
        total_size=total_size,
        buy_size=buy_size,
        sell_size=sell_size,
    )


def aggregate_trades_microstructure(trades: Any) -> dict[str, Any]:
    """Aggregate a ``trades`` table into raw microstructure signals.

    Parameters
    ----------
    trades:
        Either a ``pandas.DataFrame`` with at least a ``size`` column (and
        optionally a ``side`` column), or any iterable of record-like objects
        exposing ``.size`` and ``.side`` attributes. ``None`` / empty inputs
        yield the neutral default result.

    Returns
    -------
    dict
        Mapping with the keys in :data:`MICROSTRUCTURE_KEYS`. ``buy_volume_pct``
        is in ``[0, 100]`` and defaults to ``50.0`` when there is no
        directional (buy/sell) volume.
    """

    if trades is None:
        return _empty_result()

    # Detect a DataFrame structurally to avoid a hard pandas import at module
    # load time (and to accept duck-typed frames).
    if hasattr(trades, "columns") and hasattr(trades, "__len__"):
        return _aggregate_dataframe(trades)

    if isinstance(trades, Iterable):
        return _aggregate_iterable(trades)

    return _empty_result()


def fetch_symbol_trades(
    symbol: str,
    dataset: str,
    start: Any,
    end: Any,
    *,
    client: Any | None = None,
    stype_in: str = "raw_symbol",
) -> pd.DataFrame:
    """Fetch a single symbol's ``trades`` stream as a DataFrame (live I/O).

    Thin wrapper around the shared, retry-wrapped Databento range fetch in
    :mod:`databento_client`. Not unit-tested: it requires the ``trades``
    entitlement and performs network I/O. Inject ``client`` to reuse a
    pre-built ``Historical`` instance.
    """

    from databento_client import (
        _databento_get_range_with_retry,
        _make_databento_client,
    )

    client = client or _make_databento_client()
    store = _databento_get_range_with_retry(
        client,
        context=f"trades:{dataset}:{symbol}",
        dataset=dataset,
        schema="trades",
        symbols=[symbol],
        start=start,
        end=end,
        stype_in=stype_in,
    )
    return store.to_df()


def fetch_symbol_microstructure(
    symbol: str,
    dataset: str,
    start: Any,
    end: Any,
    *,
    client: Any | None = None,
    stype_in: str = "raw_symbol",
) -> dict[str, Any]:
    """Fetch and aggregate a symbol's trades into microstructure signals (live).

    Convenience composition of :func:`fetch_symbol_trades` and
    :func:`aggregate_trades_microstructure`. Live I/O; not unit-tested.
    """

    df = fetch_symbol_trades(
        symbol,
        dataset,
        start,
        end,
        client=client,
        stype_in=stype_in,
    )
    return aggregate_trades_microstructure(df)
