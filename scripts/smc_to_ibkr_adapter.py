"""C8/T1 — SMC setup → IBKR order intent adapter.

Pure transformation layer between the SMC inference layer (which
produces ``setup_records`` with ``entry``, ``stop_loss`` and
``take_profit`` levels) and the existing IBKR execution pipeline,
which expects :class:`scripts.execute_ibkr_watchlist.IBKROrderIntent`
instances.

This module **does not** talk to TWS / the IB Gateway. It only builds
an in-memory list of intents that the existing
``place_order_intents_with_ib`` plumbing can submit. Side-effect-free
adapters are dramatically easier to test, which is exactly what we need
for the Phase-A live-incubation gate.

Phase-B safety rails baked into the adapter
-------------------------------------------

* ``size_scale`` defaults to ``1.0`` for backwards-compatibility, but
  callers in the live-incubation runner pin it to ``0.10`` (10% of the
  full backtest size) so a wiring bug cannot put on a full-size live
  position.
* ``paper_mode`` flips the IBKR port from ``7496`` (real money) to
  ``7497`` (paper) and is exposed for tests; the actual connection is
  established by the downstream executor, the adapter just records the
  intended port so the audit log is complete.
* ``stop_loss == entry_price`` is rejected with ``ValueError`` because a
  zero-risk order silently bypasses every per-trade-loss limit
  downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from scripts.execute_ibkr_watchlist import IBKROrderIntent

PAPER_TRADING_PORT = 7497
LIVE_TRADING_PORT = 7496

# Phase-B default — caller must opt in to anything larger.
DEFAULT_SIZE_SCALE = 1.0
PHASE_B_RECOMMENDED_SIZE_SCALE = 0.10


@dataclass(frozen=True)
class IBKRAdapterConfig:
    """Connection metadata that the adapter stamps onto every intent.

    IBKR-audit 2026-06-11 (S6): renamed from ``IBKRExecutionConfig`` to
    disambiguate from the *unrelated* class of the same name in
    ``scripts.execute_ibkr_watchlist`` (tif/exchange/exit_mode). The old
    name remains importable as a backwards-compatible alias below.
    """

    host: str = "127.0.0.1"
    paper_mode: bool = True
    client_id: int = 1

    @property
    def port(self) -> int:
        """Resolve the TWS / IB Gateway port from the trading mode."""
        return PAPER_TRADING_PORT if self.paper_mode else LIVE_TRADING_PORT


# Backwards-compatible alias — existing callers/tests import this name.
IBKRExecutionConfig = IBKRAdapterConfig


def build_ibkr_intents_from_smc_setups(
    setup_records: Sequence[dict[str, Any]],
    execution_cfg: IBKRAdapterConfig,
    *,
    size_scale: float = DEFAULT_SIZE_SCALE,
) -> list[IBKROrderIntent]:
    """Translate SMC setup dicts into :class:`IBKROrderIntent` instances.

    Parameters
    ----------
    setup_records
        Iterable of dicts with at minimum ``symbol``, ``entry``,
        ``stop_loss``, ``take_profit``, ``quantity`` and ``trade_date``.
        Optional keys: ``level_tag``, ``watchlist_rank``,
        ``trailing_stop_pct``, ``tif``, ``exit_mode``, ``outside_rth``,
        ``order_ref``, ``premarket_last``, ``gap_pct``.
    execution_cfg
        IBKR connection metadata. Currently used only for the
        ``order_ref`` annotation and as a documentation seam — the
        downstream executor still resolves host/port from its own
        config object.
    size_scale
        Multiplier on the per-setup ``quantity``. Phase-B incubation
        callers should pin this to ``PHASE_B_RECOMMENDED_SIZE_SCALE``.
        Must be in the half-open interval ``(0.0, 1.0]``; values
        outside the range raise ``ValueError`` so a typo cannot silently
        ramp size.

    Returns
    -------
    list[IBKROrderIntent]
        One intent per input record, in the original order.
    """
    if not (0.0 < size_scale <= 1.0):
        raise ValueError(
            f"size_scale must be in (0.0, 1.0]; got {size_scale!r}"
        )

    intents: list[IBKROrderIntent] = []
    for idx, record in enumerate(setup_records):
        intents.append(_build_one_intent(record, execution_cfg, size_scale, idx))
    return intents


def _build_one_intent(
    record: dict[str, Any],
    execution_cfg: IBKRAdapterConfig,
    size_scale: float,
    fallback_rank: int,
) -> IBKROrderIntent:
    """Convert a single SMC setup record into an :class:`IBKROrderIntent`."""
    symbol = _required_str(record, "symbol")
    entry_price = _required_float(record, "entry")
    stop_loss = _required_float(record, "stop_loss")
    take_profit = _required_float(record, "take_profit")
    raw_quantity = int(_required_float(record, "quantity"))
    trade_date = _coerce_trade_date(record.get("trade_date"))

    # C-sprint deep-review pass-3 (Phase-B defense-in-depth): reject
    # non-positive quantities at the boundary. The previous code path
    # ``max(1, int(round(raw_quantity * size_scale)))`` silently mapped
    # zero or negative inputs to a phantom 1-share order, which would
    # bypass every per-trade-loss limit downstream and could submit
    # an order to IBKR even when the SMC layer flagged the setup as
    # invalid. A non-positive quantity always indicates an upstream
    # defect, so we fail loud here rather than absorb it.
    if raw_quantity <= 0:
        raise ValueError(
            f"quantity must be positive for {symbol!r}; got {raw_quantity!r}. "
            "Zero / negative quantity indicates an upstream SMC-layer defect."
        )

    if stop_loss == entry_price:
        raise ValueError(
            f"stop_loss must differ from entry for {symbol!r}; "
            "zero-risk orders bypass per-trade loss limits"
        )
    # Float-tolerance guard: a stop *less than* 1bp (1e-4 = 0.01%) from
    # entry is effectively a zero-risk trade and divides by ~zero in the
    # R-multiple. Anchor at max(|entry|, 1.0) so sub-dollar prices keep
    # an absolute floor. The strict ``<`` matches the wording in the
    # error message: anything *equal to or above* 1bp passes.
    if abs(stop_loss - entry_price) < 1e-4 * max(abs(entry_price), 1.0):
        raise ValueError(
            f"stop_loss less than 1bp from entry for {symbol!r}; reject as zero-risk"
        )

    scaled_quantity = max(1, round(raw_quantity * size_scale))

    return IBKROrderIntent(
        trade_date=trade_date,
        symbol=symbol,
        watchlist_rank=int(record.get("watchlist_rank", fallback_rank)),
        level_tag=str(record.get("level_tag", "smc_setup")),
        quantity=scaled_quantity,
        entry_limit=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        trailing_stop_pct=float(record.get("trailing_stop_pct", 0.0)),
        trailing_stop_anchor=float(record.get("trailing_stop_anchor", entry_price)),
        premarket_last=float(record.get("premarket_last", entry_price)),
        gap_pct=float(record.get("gap_pct", 0.0)),
        tif=str(record.get("tif", "DAY")),
        outside_rth=bool(record.get("outside_rth", False)),
        # IBKR-audit 2026-06-11 (S6): default was "bracket", a mode the
        # downstream executor does not know (it only accepts "tp-stop" /
        # "tp-trail" and raises ValueError otherwise). Default to the
        # executor-supported standard bracket mode instead.
        exit_mode=str(record.get("exit_mode", "tp-stop")),
        order_ref=str(
            record.get(
                "order_ref",
                f"smc-{symbol}-{trade_date.isoformat()}-port{execution_cfg.port}",
            )
        ),
    )


def _required_str(record: dict[str, Any], key: str) -> str:
    if key not in record or record[key] in (None, ""):
        raise ValueError(f"missing required field {key!r} in setup record")
    return str(record[key])


def _required_float(record: dict[str, Any], key: str) -> float:
    if key not in record or record[key] is None:
        raise ValueError(f"missing required field {key!r} in setup record")
    try:
        return float(record[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"field {key!r} must be numeric; got {record[key]!r}"
        ) from exc


def _coerce_trade_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(
        f"trade_date must be a date or ISO string; got {value!r}"
    )


__all__ = [
    "DEFAULT_SIZE_SCALE",
    "LIVE_TRADING_PORT",
    "PAPER_TRADING_PORT",
    "PHASE_B_RECOMMENDED_SIZE_SCALE",
    "IBKRAdapterConfig",
    "IBKRExecutionConfig",
    "build_ibkr_intents_from_smc_setups",
]
