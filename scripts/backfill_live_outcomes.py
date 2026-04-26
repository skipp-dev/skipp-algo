"""C8/T5 — Outcome backfill hook for the Phase-B live-incubation pipeline.

The live-incubation runner (C8/T3) writes ``cache/live/incubation_<date>.jsonl``
with one record per submitted intent and per fill. After a trade
closes, this module post-processes the JSONL stream and stamps the
realised PnL and R-multiple onto each closed trade so the calibration
feedback loop in C2-C6 can re-train against real fills, not just
back-tested ones.

This module is intentionally I/O-narrow:

* **Inputs.** A Phase-B JSONL file written by the live runner. Each
  line is a JSON object that must contain at least ``intent_id``,
  ``action``, ``entry_price``, ``stop_loss``, ``fill_price`` and
  ``size_usd``. Optional ``close_price`` and ``close_action`` come from
  the executor's reconcile-fills stage.
* **Outputs.** The same JSONL file, atomically rewritten, with
  ``outcome_pnl_usd`` and ``outcome_r_multiple`` populated on every
  ``filled``-then-closed pair. Records that have not yet closed are
  passed through unchanged.

There is no network access, no IBKR client, and no clock. That makes
the hook fast and trivially testable, and lets us call it from a cron
job without coupling to a TWS session.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

R_MULTIPLE_KEY = "outcome_r_multiple"
PNL_KEY = "outcome_pnl_usd"

# Actions the live runner uses to mark a trade as closed.
_CLOSED_ACTIONS = frozenset({"closed", "stop_hit", "tp_hit", "flattened"})


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file. Skip blank lines; raise on malformed JSON."""
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"malformed JSON in {path} line {line_no}: {exc.msg}"
                ) from exc
            if not isinstance(obj, dict):
                raise ValueError(
                    f"expected JSON object on {path} line {line_no}; got {type(obj).__name__}"
                )
            records.append(obj)
    return records


def _atomic_write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write JSONL records atomically to ``path`` (tmpfile + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, sort_keys=True))
                fh.write("\n")
            # C-sprint deep-review: flush+fsync before os.replace so a
            # crash between buffer-write and disk-sync does not leave
            # a truncated outcome ledger (downstream calibration
            # producers treat each line as a committed outcome).
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def compute_trade_outcome(
    *,
    entry_price: float,
    stop_loss: float,
    close_price: float,
    size_usd: float,
) -> tuple[float, float]:
    """Return ``(pnl_usd, r_multiple)`` for a long-only Phase-B trade.

    The R-multiple is ``(close - entry) / (entry - stop)``. A close at
    the entry yields ``0R``, a close at the take-profit yields ``+1R``
    if the TP was placed at ``entry + (entry - stop)``, and a stop-out
    yields ``-1R``. The PnL in USD is the R-multiple scaled by the
    notional risk per trade (``size_usd / leverage`` is *not* applied —
    the live runner already records the realised dollar exposure).

    Raises
    ------
    ValueError
        If ``entry_price == stop_loss`` (zero-risk trade — this should
        have been blocked by ``smc_to_ibkr_adapter`` already; defence
        in depth).
    """
    risk_per_share = entry_price - stop_loss
    if risk_per_share == 0:
        raise ValueError(
            "entry_price must differ from stop_loss; zero-risk trade has no R-multiple"
        )
    pnl_per_dollar = (close_price - entry_price) / entry_price
    pnl_usd = pnl_per_dollar * size_usd
    r_multiple = (close_price - entry_price) / risk_per_share
    return pnl_usd, r_multiple


def _backfill_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``record`` with outcome fields populated if possible."""
    if PNL_KEY in record and record[PNL_KEY] is not None:
        return record  # already backfilled, idempotent.
    action = record.get("action")
    if action not in _CLOSED_ACTIONS:
        return record  # trade not yet closed.
    try:
        entry_price = float(record["entry_price"])
        stop_loss = float(record["stop_loss"])
        size_usd = float(record["size_usd"])
        close_price = float(record["close_price"])
    except (KeyError, TypeError, ValueError):
        # Missing / non-numeric fields — leave the record as-is so the
        # operator can fix the upstream stream rather than silently
        # dropping the trade.
        return record

    pnl_usd, r_multiple = compute_trade_outcome(
        entry_price=entry_price,
        stop_loss=stop_loss,
        close_price=close_price,
        size_usd=size_usd,
    )
    out = dict(record)
    out[PNL_KEY] = pnl_usd
    out[R_MULTIPLE_KEY] = r_multiple
    return out


def backfill_live_outcomes(path: Path | str) -> dict[str, int]:
    """Backfill outcome fields for every closed live trade in ``path``.

    Returns a small summary dict::

        {
            "records_total": <int>,
            "records_backfilled": <int>,
            "records_already_resolved": <int>,
            "records_pending_close": <int>,
        }

    The summary is useful for cron-job logging and CI assertions.
    """
    p = Path(path)
    records = _load_jsonl(p)
    summary = {
        "records_total": len(records),
        "records_backfilled": 0,
        "records_already_resolved": 0,
        "records_pending_close": 0,
    }
    out: list[dict[str, Any]] = []
    for record in records:
        already = record.get(PNL_KEY) is not None
        action = record.get("action")
        if already:
            summary["records_already_resolved"] += 1
            out.append(record)
            continue
        if action not in _CLOSED_ACTIONS:
            summary["records_pending_close"] += 1
            out.append(record)
            continue
        new_record = _backfill_record(record)
        if new_record.get(PNL_KEY) is not None:
            summary["records_backfilled"] += 1
        out.append(new_record)

    _atomic_write_jsonl(p, out)
    return summary


__all__ = [
    "PNL_KEY",
    "R_MULTIPLE_KEY",
    "backfill_live_outcomes",
    "compute_trade_outcome",
]
