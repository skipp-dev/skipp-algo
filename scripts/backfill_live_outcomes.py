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
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

R_MULTIPLE_KEY = "outcome_r_multiple"
PNL_KEY = "outcome_pnl_usd"

# C13/T8.3 — opening-auction imbalance annotation keys (additive). The
# imbalance loader is a Phase-A passive enrichment; downstream
# consumers must treat the keys as optional (NASDAQ trades never
# carry them because IBKR has no NASDAQ-imbalance subscription).
IMBALANCE_SIDE_KEY = "opening_imbalance_side"
IMBALANCE_NORMALIZED_KEY = "opening_imbalance_shares_normalized"
IMBALANCE_FEED_KEY = "opening_imbalance_feed"
IMBALANCE_AVAILABLE_KEY = "opening_imbalance_available"

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
            "records_audit_only": <int>,
        }

    ``records_audit_only`` (2026-06-10, F-V3-15 follow-up) is the subset
    of ``records_pending_close`` whose ``action == "audit_only"`` —
    journaled intents that never reached a broker (C13 T1 NO-GO) and
    can structurally never close. The cron's progress assertion must
    not treat them as "stuck pending" or the known NO-GO condition
    would masquerade as an auth/quota regression (and hard-fail the
    cron daily once F-V3-15 phase 2 lands).

    The summary is useful for cron-job logging and CI assertions.
    """
    p = Path(path)
    records = _load_jsonl(p)
    summary = {
        "records_total": len(records),
        "records_backfilled": 0,
        "records_already_resolved": 0,
        "records_pending_close": 0,
        "records_audit_only": 0,
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
            if action == "audit_only":
                summary["records_audit_only"] += 1
            out.append(record)
            continue
        new_record = _backfill_record(record)
        if new_record.get(PNL_KEY) is not None:
            summary["records_backfilled"] += 1
        out.append(new_record)

    _atomic_write_jsonl(p, out)
    return summary


def annotate_imbalance_outcomes(
    audit_path: Path | str,
    *,
    imbalance_index: dict[str, dict[str, Any]],
    avg_volume_lookup: dict[str, float] | None = None,
) -> dict[str, int]:
    """Annotate audit-log rows with opening-imbalance metadata.

    Phase-A T8.3 contract: annotation is **purely additive**. Every
    audit row that carries a ``symbol`` field is considered —
    intent-creations, fills, halts, closes, etc. The downstream
    correlator/stratifier re-filters on its own action set, so this
    hook does not gate on ``closed`` / ``filled`` / ``outcome_pnl_usd``
    on its own. Rows without a ``symbol`` are passed through
    unchanged.

    Parameters
    ----------
    audit_path:
        Path to a backfilled audit JSONL (run :func:`backfill_live_outcomes`
        first to ensure outcome fields are present; this hook does not
        require them but the producer order is the canonical one).
    imbalance_index:
        Mapping ``symbol`` (UPPERCASE) -> imbalance-snapshot dict from
        :mod:`scripts.imbalance_data`. Snapshots without
        ``auction_imbalance_shares`` set are treated as unavailable.
    avg_volume_lookup:
        Optional ``symbol`` -> 30d-avg-daily-volume mapping used for the
        ``opening_imbalance_shares_normalized`` field. When omitted the
        normalised value is left as ``None`` and only the raw side flag
        is written.

    Returns
    -------
    dict
        Summary counts:: ``records_total``, ``records_annotated``,
        ``records_skipped_no_data``, ``records_skipped_unavailable``.

    The function is idempotent.
    """
    p = Path(audit_path)
    records = _load_jsonl(p)
    avg_volume_lookup = {
        str(k).upper(): float(v)
        for k, v in (avg_volume_lookup or {}).items()
    }
    summary = {
        "records_total": len(records),
        "records_annotated": 0,
        "records_skipped_no_data": 0,
        "records_skipped_unavailable": 0,
    }
    out: list[dict[str, Any]] = []
    for record in records:
        symbol_raw = record.get("symbol")
        if not symbol_raw:
            out.append(record)
            continue
        sym = str(symbol_raw).upper()
        snapshot = imbalance_index.get(sym)
        if snapshot is None:
            summary["records_skipped_no_data"] += 1
            out.append(record)
            continue
        side = snapshot.get("auction_imbalance_side") or "NEUTRAL"
        shares = snapshot.get("auction_imbalance_shares")
        feed = snapshot.get("imbalance_feed")
        available = bool(snapshot.get("available"))
        if not available or shares is None:
            summary["records_skipped_unavailable"] += 1
            new_record = dict(record)
            new_record[IMBALANCE_AVAILABLE_KEY] = False
            new_record[IMBALANCE_FEED_KEY] = feed
            out.append(new_record)
            continue
        normalised = None
        avg_vol = avg_volume_lookup.get(sym)
        if avg_vol and avg_vol > 0:
            try:
                normalised = float(shares) / float(avg_vol)
            except (TypeError, ValueError):
                normalised = None
        new_record = dict(record)
        new_record[IMBALANCE_AVAILABLE_KEY] = True
        new_record[IMBALANCE_SIDE_KEY] = side
        new_record[IMBALANCE_NORMALIZED_KEY] = normalised
        new_record[IMBALANCE_FEED_KEY] = feed
        summary["records_annotated"] += 1
        out.append(new_record)

    _atomic_write_jsonl(p, out)
    return summary


def load_imbalance_index(jsonl_path: Path | str) -> dict[str, dict[str, Any]]:
    """Read an imbalance JSONL and return a ``symbol -> snapshot`` map.

    Used as the ``imbalance_index`` argument to
    :func:`annotate_imbalance_outcomes`. Tolerant by design: malformed
    JSON lines and rows without a ``symbol`` field are skipped with a
    log warning so a single corrupt line does not block the whole
    daily-cron annotation step. The strict reader
    (:func:`_load_jsonl`) is used by the outcome backfill itself,
    where partial files must abort.
    """
    out: dict[str, dict[str, Any]] = {}
    p = Path(jsonl_path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "load_imbalance_index: skipping malformed line %d in %s: %s",
                    line_no,
                    p,
                    exc.msg,
                )
                continue
            if not isinstance(obj, dict):
                logger.warning(
                    "load_imbalance_index: skipping non-object line %d in %s",
                    line_no,
                    p,
                )
                continue
            sym_raw = obj.get("symbol")
            if not sym_raw:
                continue
            out[str(sym_raw).upper()] = obj
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: backfill outcomes for one audit JSONL.

    Usage::

        python -m scripts.backfill_live_outcomes <audit.jsonl> \
            [--imbalance-index <imbalance.jsonl>]

    Without the optional ``--imbalance-index`` flag the runner only
    backfills outcome fields (``backfill_live_outcomes``); when an
    imbalance index is provided it also annotates each row in place
    via ``annotate_imbalance_outcomes``. Returns 0 on success and a
    non-zero exit code on argument or I/O errors so the c13-daily-cron
    workflow can gate downstream steps on the return value.
    """
    # F-V8-A1.3 (2026-05-02): bootstrap root logging so the logger.info(...)
    # progress messages this entry point emits actually surface in CI logs
    # (default WARNING-only handler would drop them). Carries forward F-CI-O1.
    try:
        from scripts._logging_init import init_cli_logging
    except ImportError:  # script-style invocation: `python scripts/X.py`
        import sys as _v8a13_sys
        from pathlib import Path as _v8a13_Path

        _v8a13_sys.path.insert(0, str(_v8a13_Path(__file__).resolve().parents[1]))
        from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]
    init_cli_logging()

    import argparse

    parser = argparse.ArgumentParser(
        prog="scripts.backfill_live_outcomes",
        description=(
            "Backfill outcome fields (and optionally opening-imbalance "
            "annotations) for a live-incubation audit JSONL."
        ),
    )
    parser.add_argument(
        "audit_path",
        type=Path,
        help="Path to the live-incubation audit JSONL to backfill in place.",
    )
    parser.add_argument(
        "--imbalance-index",
        type=Path,
        default=None,
        help=(
            "Optional imbalance JSONL produced by "
            "scripts.collect_opening_imbalances; when supplied, audit rows "
            "are also annotated with imbalance metadata."
        ),
    )
    args = parser.parse_args(argv)

    audit = args.audit_path
    if not audit.is_file():
        logger.error("audit file %s does not exist", audit)
        return 2

    summary = backfill_live_outcomes(audit)
    logger.info("backfill summary: %s", summary)
    print(json.dumps({"backfill": summary}, sort_keys=True))

    if args.imbalance_index is not None:
        if not args.imbalance_index.is_file():
            logger.error(
                "imbalance index %s does not exist", args.imbalance_index
            )
            return 2
        index = load_imbalance_index(args.imbalance_index)
        ann_summary = annotate_imbalance_outcomes(
            audit, imbalance_index=index
        )
        logger.info("annotation summary: %s", ann_summary)
        print(json.dumps({"annotation": ann_summary}, sort_keys=True))

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())


__all__ = [
    "IMBALANCE_AVAILABLE_KEY",
    "IMBALANCE_FEED_KEY",
    "IMBALANCE_NORMALIZED_KEY",
    "IMBALANCE_SIDE_KEY",
    "PNL_KEY",
    "R_MULTIPLE_KEY",
    "annotate_imbalance_outcomes",
    "backfill_live_outcomes",
    "compute_trade_outcome",
    "load_imbalance_index",
    "main",
]
