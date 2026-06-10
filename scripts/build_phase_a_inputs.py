"""C13 Phase-A — daily inputs producer for ``run_smc_live_incubation.py``.

Reads the latest ``reports/open_prep_trade_cards_*.csv`` (produced by
``scripts/export_open_prep_lists.py``) and emits the two artefacts the
live-incubation orchestrator expects:

* ``cache/live/setups_<DATE>.jsonl``  — list of setup-record dicts with
  ``variant``, ``symbol``, ``entry``, ``stop_loss``, ``take_profit``,
  ``quantity``, ``trade_date`` (schema mirrors ``tests/test_run_smc_live_incubation.py::_setup``).
* ``cache/live/gate_status.json`` — ``{variant_key: "green"|"amber"|"red"}``.
  Cold-start defaults to ``amber`` for every observed variant so the
  orchestrator emits ``audit_only`` records (Phase-A is paper-only —
  see C13 sprint plan ``docs/sprints/c13_live_incubation_phase_a.md``).

Phase-A is strictly ``--phase paper``; this producer never sets a
variant to ``green``. Promotion to green is gated by the track-record
verdict from ``scripts/track_record_gate.py`` and is a Phase-B decision.

Risk-multiple convention:

* ``entry``       = ``stop_reference_price``   (last close at OPRA snapshot)
* ``stop_loss``   = ``stop_mid``               (mid-tier ATR-anchored stop)
* ``take_profit`` = ``entry + 2 * (entry - stop_loss)``  (2R target, long only)

The trade-cards CSV emits long setups exclusively today; short support
will be added when ``setup_type`` includes a ``short`` direction.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.smc_atomic_write import atomic_write_json, atomic_write_text

# Map open_prep ``setup_type`` strings → live-incubation variant keys.
# The mapping is intentionally narrow: any unmapped setup_type raises
# during the build so a typo or new setup family is caught instead of
# silently bypassing the gate-status mechanism.
_SETUP_TYPE_TO_VARIANT: dict[str, str] = {
    "ORB or VWAP-Hold": "smc_orb_vwap_hold",
}


# Maximum number of calendar days a trade-cards CSV may be older than the
# requested trade_date before it is considered stale.  Mirrors the 4-day
# staleness cap applied to the WSH earnings snapshot in
# run-c13-phase-a.sh (B1, audit pass-4, 2026-06-10).
_MAX_TRADE_CARDS_AGE_DAYS: int = 4


def _trade_cards_age_days(csv_path: Path, trade_date: str) -> int | None:
    """Return age in calendar days of *csv_path* relative to *trade_date*.

    The filename must contain an ISO-date substring (``YYYY-MM-DD``).
    Returns ``None`` when the date cannot be parsed — callers treat that
    as indefinitely stale.
    """
    import re

    m = re.search(r"(\d{4}-\d{2}-\d{2})", csv_path.name)
    if not m:
        return None
    try:
        file_date = date.fromisoformat(m.group(1))
        ref_date = date.fromisoformat(trade_date)
        return (ref_date - file_date).days
    except ValueError:
        return None


def _latest_trade_cards(reports_dir: Path, trade_date: str | None = None) -> Path:
    """Return the newest trade-cards CSV, rejecting files older than
    ``_MAX_TRADE_CARDS_AGE_DAYS`` relative to *trade_date*.

    When *trade_date* is ``None`` the staleness check is skipped (used
    by tests that construct synthetic paths without a date reference).
    Mirrors the WSH 4-day staleness cap in ``run-c13-phase-a.sh`` so
    stale entry/stop prices are never silently stamped with today's date
    (B1, audit pass-4, 2026-06-10).
    """
    candidates = sorted(reports_dir.glob("open_prep_trade_cards_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No open_prep_trade_cards_*.csv found in {reports_dir}; "
            "run scripts/export_open_prep_lists.py first."
        )
    newest = candidates[-1]
    if trade_date is not None:
        age = _trade_cards_age_days(newest, trade_date)
        if age is None or age > _MAX_TRADE_CARDS_AGE_DAYS:
            age_str = f"{age}d" if age is not None else "unparseable date"
            raise FileNotFoundError(
                f"Newest trade-cards CSV {newest.name} is {age_str} old "
                f"(>{_MAX_TRADE_CARDS_AGE_DAYS}d relative to trade_date "
                f"{trade_date}); re-run export_open_prep_lists.py or pass "
                "--trade-cards-csv explicitly. Refusing to stamp stale "
                "prices with today's trade_date."
            )
    return newest


def _required_float(row: dict[str, str], key: str) -> float:
    raw = row.get(key, "")
    if raw == "" or raw is None:
        raise ValueError(f"missing {key!r} in trade-cards row: {row}")
    return float(raw)


def _row_to_setup(
    row: dict[str, str],
    *,
    trade_date: str,
    quantity: int,
) -> dict[str, Any]:
    setup_type = (row.get("setup_type") or "").strip()
    try:
        variant = _SETUP_TYPE_TO_VARIANT[setup_type]
    except KeyError as exc:
        raise ValueError(
            f"unmapped setup_type {setup_type!r}; "
            f"add it to _SETUP_TYPE_TO_VARIANT in build_phase_a_inputs.py"
        ) from exc

    symbol = (row.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError(f"empty symbol in trade-cards row: {row}")

    entry = _required_float(row, "stop_reference_price")
    stop_loss = _required_float(row, "stop_mid")

    if stop_loss >= entry:
        # Long-only today; a stop at-or-above entry would be a short
        # setup or a malformed row. Reject loudly per the
        # ``smc_to_ibkr_adapter`` boundary contract.
        raise ValueError(
            f"stop_mid ({stop_loss}) >= stop_reference_price ({entry}) "
            f"for {symbol!r}; long-only producer cannot emit short setup"
        )

    risk_per_share = entry - stop_loss
    take_profit = entry + 2.0 * risk_per_share

    return {
        "variant": variant,
        "symbol": symbol,
        "entry": round(entry, 4),
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "quantity": int(quantity),
        "trade_date": trade_date,
    }


def build_setups_from_trade_cards(
    trade_cards_csv: Path,
    *,
    trade_date: str,
    quantity: int = 1,
) -> list[dict[str, Any]]:
    """Read a trade-cards CSV and return a list of setup records."""
    setups: list[dict[str, Any]] = []
    with trade_cards_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            setups.append(_row_to_setup(row, trade_date=trade_date, quantity=quantity))
    return setups


def build_gate_status(setups: list[dict[str, Any]]) -> dict[str, str]:
    """Cold-start gate-status: every observed variant → ``amber``.

    Phase-A is paper-only so ``amber`` is the safest default — the
    orchestrator still routes the setup through the audit pipeline but
    never escalates to a live submit. Promotion to ``green`` requires a
    real track-record verdict (Phase-B).
    """
    return {setup["variant"]: "amber" for setup in setups}


def _parse_trade_date(raw: str | None) -> str:
    """Validate and normalise the ``--trade-date`` CLI value.

    Treats an empty / ``None`` value as "today UTC" and otherwise parses
    via :func:`date.fromisoformat`. Returning the round-tripped
    ``isoformat()`` value rejects path-traversal payloads (``../``) and
    locale-specific date strings before they can land in record fields
    or in the ``setups_<DATE>.jsonl`` filename.
    """

    if raw is None or raw == "":
        return datetime.now(UTC).date().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise SystemExit(
            f"--trade-date must be ISO-8601 (YYYY-MM-DD); got {raw!r}"
        ) from exc


def _positive_quantity(raw: str) -> int:
    """Argparse type for ``--quantity``: must be a positive integer.

    The downstream IBKR adapter (``scripts/smc_to_ibkr_adapter.py``)
    rejects non-positive quantities at submit time; failing fast here
    keeps the artefact files (and the live runner's audit trail) free
    of records that are guaranteed to be rejected later.
    """

    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--quantity must be an integer; got {raw!r}"
        ) from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(
            f"--quantity must be > 0; got {value}"
        )
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_phase_a_inputs",
        description=(
            "Produce cache/live/setups_<DATE>.jsonl + gate_status.json "
            "from the latest reports/open_prep_trade_cards_*.csv."
        ),
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reports",
        help="Directory containing open_prep_trade_cards_*.csv (default: ./reports).",
    )
    parser.add_argument(
        "--trade-cards-csv",
        type=Path,
        default=None,
        help="Explicit trade-cards CSV path (overrides --reports-dir auto-discovery).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "cache" / "live",
        help="Output directory for setups + gate_status (default: ./cache/live).",
    )
    parser.add_argument(
        "--trade-date",
        type=str,
        default=None,
        help="Trade date (YYYY-MM-DD). Defaults to today UTC.",
    )
    parser.add_argument(
        "--quantity",
        type=_positive_quantity,
        default=1,
        help="Per-setup quantity (positive int; Phase-A audit-only; default 1).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    trade_date = _parse_trade_date(args.trade_date)

    csv_path = args.trade_cards_csv or _latest_trade_cards(
        args.reports_dir, trade_date=trade_date
    )
    setups = build_setups_from_trade_cards(
        csv_path, trade_date=trade_date, quantity=args.quantity
    )
    if not setups:
        # Phase-A never blocks on data unavailability — emit empty
        # artefacts so the cron job exits 0 and downstream consumers
        # see "no setups today" rather than a stale yesterday-file.
        print(
            f"WARN: no setups derived from {csv_path}; writing empty inputs",
            file=sys.stderr,
        )

    gate_status = build_gate_status(setups)

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    setups_path = args.cache_dir / f"setups_{trade_date}.jsonl"
    gate_path = args.cache_dir / "gate_status.json"

    # The live runner does ``json.loads(args.setups.read_text(...))`` so
    # the on-disk format is a JSON list (despite the ``.jsonl`` suffix
    # the runbook uses). Keep the suffix for forward-compatibility with
    # a future line-delimited variant.
    atomic_write_text(json.dumps(setups, indent=2, sort_keys=True), setups_path)
    atomic_write_json(gate_status, gate_path, sort_keys=True)

    summary = {
        "trade_date": trade_date,
        "trade_cards_csv": str(csv_path),
        "setups_path": str(setups_path),
        "gate_status_path": str(gate_path),
        "n_setups": len(setups),
        "variants_amber": sorted(gate_status),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
