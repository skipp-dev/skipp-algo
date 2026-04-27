"""C13 / Phase-A — Pre-open producer for ``setups`` + ``gate_status`` inputs.

Produces the two JSON files consumed by ``scripts.run_smc_live_incubation``:

* ``setups_<DATE>.jsonl`` — one JSON object per line, each a setup-record
  with ``symbol``, ``entry``, ``stop_loss``, ``take_profit``, ``quantity``,
  ``trade_date``, ``variant`` (the schema accepted by
  :func:`scripts.smc_to_ibkr_adapter.build_ibkr_intents_from_smc_setups`).
* ``gate_status_<DATE>.json`` — flat ``{variant: "green"|"amber"|"red"|"skipped"}``
  mapping consumed by the live-incubation runner's ``--gate-statuses`` arg.

Phase-A seeding contract
------------------------

In Phase-A the producer is intentionally **honest about absent data**:

* If no ``--returns`` payload is supplied (or it is missing
  ``returns_by_variant``), the gate file maps every known variant to
  ``skipped`` rather than fabricating verdicts — the live-incubation
  runner will then drop every setup as untradable, which is the safe
  default until C2/C3 have filled the per-variant returns history.
* If no ``--setups-source`` payload is supplied, ``setups_<DATE>.jsonl``
  is written as an **empty file** with a sidecar ``.meta.json`` carrying
  ``{"phase_a_seed": true}``. The audit log then records zero intents,
  which is the correct Phase-A behaviour while the SMC quote-feed
  ingestion is still being wired in (tracked as C14 backlog).

The script is **idempotent**: running it twice on the same trade-date
overwrites the prior outputs atomically (tempfile + ``os.replace``) and
never partially-truncates an existing file.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

# Re-use the same per-variant gate evaluator that drives the dashboard
# and the public report (single source of truth — no parallel scoring
# logic in the Phase-A producer).
from scripts.track_record_gate import evaluate_track_record_gate_per_variant

SCHEMA_VERSION = "1.0.0"

# Map the gate's internal traffic-light vocab ("yellow") to the live-
# incubation runner's vocab ("amber"). Mirrors
# ``scripts.build_dashboard_payload._gate_status_from_track_record``.
_GATE_STATUS_REMAP = {
    "green": "green",
    "yellow": "amber",
    "amber": "amber",
    "red": "red",
    "skipped": "skipped",
}


# --------------------------------------------------------------------------- #
# Atomic writers                                                              #
# --------------------------------------------------------------------------- #


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via tempfile + fsync + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _atomic_write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    """Write ``records`` as one JSON object per line. An empty list yields
    an empty file (zero bytes), which is the Phase-A seed contract."""
    if not records:
        _atomic_write_text(path, "")
        return
    lines = [json.dumps(r, sort_keys=True) for r in records]
    _atomic_write_text(path, "\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Setup-record validation                                                     #
# --------------------------------------------------------------------------- #


_REQUIRED_SETUP_KEYS = (
    "symbol",
    "entry",
    "stop_loss",
    "take_profit",
    "quantity",
    "trade_date",
    "variant",
)


def _validate_setup_record(record: Any, idx: int) -> dict[str, Any]:
    """Reject malformed setup records *before* they reach the runner.

    The runner's adapter will eventually raise too, but failing here
    means the LaunchAgent log carries the trade-date + record-index of
    the offender, which is much easier to debug at 09:25 ET than a
    backtrace from inside the audit-write step.
    """

    if not isinstance(record, dict):
        raise ValueError(f"setup-record #{idx}: expected JSON object, got {type(record).__name__}")
    missing = [k for k in _REQUIRED_SETUP_KEYS if k not in record]
    if missing:
        raise ValueError(
            f"setup-record #{idx}: missing required keys: {missing!r}. Required schema: {list(_REQUIRED_SETUP_KEYS)!r}"
        )
    return dict(record)


def _load_setups_source(path: Path | None, trade_date: date) -> list[dict[str, Any]]:
    """Load + validate the upstream setup-records.

    ``path`` is optional: in Phase-A seeding mode the upstream SMC
    quote-feed ingestion is not yet wired (C14 backlog), so we accept
    "no input file" as "produce an empty setups file".
    """
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON list of setup-records at top level")
    out: list[dict[str, Any]] = []
    iso = trade_date.isoformat()
    for idx, record in enumerate(raw):
        validated = _validate_setup_record(record, idx)
        # Stamp / overwrite trade_date so the producer is the single
        # source of truth for "which session does this setup belong to".
        validated["trade_date"] = iso
        out.append(validated)
    return out


# --------------------------------------------------------------------------- #
# Gate-status producer                                                        #
# --------------------------------------------------------------------------- #


def _normalise_gate_status(raw: str) -> str:
    norm = _GATE_STATUS_REMAP.get(raw.strip().lower())
    if norm is None:
        # Defensive: any future status string the gate adds becomes
        # "skipped" so we never accidentally promote it to tradable.
        return "skipped"
    return norm


def _load_returns_payload(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: expected a JSON object at top level (see scripts/build_track_record_gate.py for the schema)"
        )
    return raw


def _build_gate_status(
    *,
    returns_payload: Mapping[str, Any] | None,
    known_variants: Sequence[str],
) -> dict[str, str]:
    """Compute the flat ``{variant: status}`` mapping.

    The mapping always covers every variant the producer knows about
    (union of ``known_variants`` and any keys present in
    ``returns_by_variant``). Variants without returns are emitted as
    ``"skipped"`` rather than dropped so the runner's
    ``_filter_tradable_setups`` sees an explicit non-tradable verdict
    and does not silently let setups through on a missing-key fallback.
    """

    by_variant: dict[str, list[float]] = {}
    if returns_payload is not None:
        raw = returns_payload.get("returns_by_variant")
        if isinstance(raw, dict):
            for variant, returns in raw.items():
                if not isinstance(variant, str):
                    continue
                if not isinstance(returns, list):
                    continue
                cleaned = [float(x) for x in returns if isinstance(x, (int, float))]
                if cleaned:
                    by_variant[variant] = cleaned

    union = sorted({*known_variants, *by_variant.keys()})

    if not by_variant:
        # No usable returns anywhere → every variant is "skipped" and
        # the runner will reject all setups. This is the documented
        # Phase-A seed state (calibration_report_public.json carries
        # status=awaiting_first_run until C2/C3 backfill the history).
        return {variant: "skipped" for variant in union}

    verdicts = evaluate_track_record_gate_per_variant(returns_by_variant=by_variant)
    out: dict[str, str] = {}
    for variant in union:
        verdict = verdicts.get(variant)
        if verdict is None:
            out[variant] = "skipped"
        else:
            out[variant] = _normalise_gate_status(str(verdict.get("status", "")))
    return out


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "C13 / Phase-A pre-open producer. Writes setups_<DATE>.jsonl and gate_status_<DATE>.json into <output-dir>."
        )
    )
    parser.add_argument(
        "--trade-date",
        type=str,
        default=None,
        help=(
            "Session date in YYYY-MM-DD. Defaults to today's UTC date. "
            "Used both as the filename suffix and to stamp setup records."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory the producer writes setups + gate-status into.",
    )
    parser.add_argument(
        "--setups-source",
        type=Path,
        default=None,
        help=(
            "Optional JSON list of upstream setup-records. Omit during Phase-A seeding to write an empty setups file."
        ),
    )
    parser.add_argument(
        "--returns",
        type=Path,
        default=None,
        help=(
            "Optional JSON file with per-variant returns "
            '({"returns_by_variant": {variant: [...]}}). Omit during '
            "Phase-A seeding to mark every variant 'skipped'."
        ),
    )
    parser.add_argument(
        "--known-variants",
        type=str,
        default="",
        help=(
            "Comma-separated list of variant keys the runner expects. "
            "Variants not present in --returns are emitted as 'skipped'. "
            "Empty by default — the producer derives the list from "
            "--returns alone."
        ),
    )
    return parser.parse_args(argv)


def _resolve_trade_date(arg: str | None) -> date:
    if arg is None:
        return datetime.now(UTC).date()
    return date.fromisoformat(arg)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    trade_date = _resolve_trade_date(args.trade_date)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    iso = trade_date.isoformat()
    setups_path = output_dir / f"setups_{iso}.jsonl"
    setups_meta_path = output_dir / f"setups_{iso}.meta.json"
    gate_path = output_dir / f"gate_status_{iso}.json"

    # 1. Setups
    setups = _load_setups_source(args.setups_source, trade_date)
    _atomic_write_jsonl(setups_path, setups)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": iso,
        "n_setups": len(setups),
        "phase_a_seed": args.setups_source is None,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write_json(setups_meta_path, meta)

    # 2. Gate-status
    returns_payload = _load_returns_payload(args.returns)
    known_variants = [v.strip() for v in args.known_variants.split(",") if v.strip()]
    gate_status = _build_gate_status(
        returns_payload=returns_payload,
        known_variants=known_variants,
    )
    _atomic_write_json(gate_path, gate_status)

    # 3. Operator-friendly stdout summary so the LaunchAgent log shows
    #    at a glance whether today's session has anything tradable.
    tradable = sorted(v for v, s in gate_status.items() if s in ("green", "amber"))
    print(
        json.dumps(
            {
                "trade_date": iso,
                "setups_path": str(setups_path),
                "setups_count": len(setups),
                "gate_status_path": str(gate_path),
                "gate_variants": len(gate_status),
                "tradable_variants": tradable,
                "phase_a_seed": meta["phase_a_seed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
