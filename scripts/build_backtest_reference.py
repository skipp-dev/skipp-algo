"""C8/T6 — Glue scripts that bridge the live-incubation audit log
to the live-vs-backtest drift detector.

Provides two related artefacts:

1. :func:`build_backtest_reference` — derives the
   ``{variant: {sharpe, hit_rate_ci_low, hit_rate_ci_high}}`` map that
   :func:`scripts.compute_live_drift.compute_live_drift` consumes from
   ``cache/calibration/backtest_reference_<date>.json``. Reads the C2
   walk-forward output + (optionally) the C3 bootstrap-CI sidecar.

2. :func:`build_drift_input_from_audit` — converts a live-incubation
   audit JSONL (with ``outcome_pnl_usd`` / ``outcome_r_multiple``
   stamped by :mod:`scripts.backfill_live_outcomes`) into the
   ``{variant, return, slippage, hit}`` row schema the drift detector
   expects. Without this adapter the audit log and the drift detector
   speak disjoint dialects and the cron silently emits an empty report.

Pure stdlib + numpy. No new external dependencies.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "build_backtest_reference",
    "build_drift_input_from_audit",
    "main_backtest_reference",
    "main_drift_input",
]


# ---------------------------------------------------------------------------
# Backtest-reference producer
# ---------------------------------------------------------------------------


def _variant_key(record: Mapping[str, Any]) -> str | None:
    """Compose the canonical ``setup_type_symbol_group`` key.

    Falls back to a single ``variant`` field if the row already carries
    one (e.g. C8 audit records produced by the live runner).
    """
    direct = record.get("variant")
    if isinstance(direct, str) and direct:
        return direct
    setup_type = record.get("setup_type")
    symbol_group = record.get("symbol_group")
    if isinstance(setup_type, str) and setup_type and isinstance(symbol_group, str) and symbol_group:
        return f"{setup_type}_{symbol_group}"
    return None


def build_backtest_reference(
    *,
    walk_forward: Mapping[str, Any] | None = None,
    bootstrap_ci: Mapping[str, Any] | None = None,
    psr_mintrl: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``{variant: {sharpe, hit_rate_ci_low, hit_rate_ci_high}}`` map.

    All three inputs are optional dicts (already-loaded JSON). Variants
    listed only in ``walk_forward`` get a sharpe entry; bootstrap CIs
    populate the hit-rate band when present.

    The output is wrapped under a top-level ``backtest_reference`` key
    so the file shape is usable both as
    ``cache/calibration/backtest_reference_<date>.json`` AND as a drop-in
    replacement for ``cache/calibration/c2_walk_forward.json`` when the
    drift CLI's ``--backtest-calibration`` argument is pointed at it.
    """

    out: dict[str, dict[str, Any]] = {}

    if walk_forward is not None:
        for variant_row in walk_forward.get("variants") or []:
            if not isinstance(variant_row, Mapping):
                continue
            key = _variant_key(variant_row)
            if key is None:
                continue
            sharpe = variant_row.get("sharpe")
            hit_rate = variant_row.get("hit_rate")
            slot = out.setdefault(key, {})
            if isinstance(sharpe, (int, float)):
                slot["sharpe"] = float(sharpe)
            if isinstance(hit_rate, (int, float)):
                slot["hit_rate"] = float(hit_rate)

    if bootstrap_ci is not None:
        for variant_row in bootstrap_ci.get("variants") or []:
            if not isinstance(variant_row, Mapping):
                continue
            key = _variant_key(variant_row)
            if key is None:
                continue
            slot = out.setdefault(key, {})
            for src_key, dst_key in (
                ("hit_rate_ci_low", "hit_rate_ci_low"),
                ("hit_rate_ci_high", "hit_rate_ci_high"),
                ("sharpe_ci_low", "sharpe_ci_low"),
                ("sharpe_ci_high", "sharpe_ci_high"),
            ):
                value = variant_row.get(src_key)
                if isinstance(value, (int, float)):
                    slot[dst_key] = float(value)

    if psr_mintrl is not None:
        for variant_row in psr_mintrl.get("variants") or []:
            if not isinstance(variant_row, Mapping):
                continue
            key = _variant_key(variant_row)
            if key is None:
                continue
            slot = out.setdefault(key, {})
            psr = variant_row.get("psr_at_0")
            if isinstance(psr, (int, float)):
                slot["psr_at_0"] = float(psr)

    return {"backtest_reference": out}


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+os.replace pattern above.
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def main_backtest_reference(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Build cache/calibration/backtest_reference_<date>.json from the "
            "C2 walk-forward + (optional) C3 bootstrap-CI artefacts."
        )
    )
    p.add_argument("--walk-forward", type=Path, required=True)
    p.add_argument("--bootstrap-ci", type=Path, default=None)
    p.add_argument("--psr-mintrl", type=Path, default=None)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)

    def _maybe_load(path: Path | None) -> dict[str, Any] | None:
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    payload = build_backtest_reference(
        walk_forward=_maybe_load(args.walk_forward),
        bootstrap_ci=_maybe_load(args.bootstrap_ci),
        psr_mintrl=_maybe_load(args.psr_mintrl),
    )
    _atomic_write_json(args.output, payload)
    print(f"wrote {args.output} ({len(payload['backtest_reference'])} variants)")
    return 0


# ---------------------------------------------------------------------------
# Audit-JSONL → drift-input adapter
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _coerce_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def build_drift_input_from_audit(
    audit_records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project audit records (post-backfill) into the drift-input schema.

    Each input record is expected to carry the fields written by
    :func:`scripts.run_smc_live_incubation._atomic_append_audit` plus
    the ``outcome_pnl_usd`` / ``outcome_r_multiple`` stamps that
    :func:`scripts.backfill_live_outcomes.backfill_live_outcomes`
    appends after a trade closes. Records without ``outcome_pnl_usd``
    are skipped (trade not yet closed).

    Returned rows match the schema documented on
    :func:`scripts.compute_live_drift.compute_live_drift`::

        {"variant": str, "return": float, "slippage": float, "hit": bool}
    """

    out: list[dict[str, Any]] = []
    for record in audit_records:
        pnl = record.get("outcome_pnl_usd")
        if pnl is None:
            continue
        variant = record.get("variant")
        if not isinstance(variant, str) or not variant:
            # Records emitted before the C8 variant-propagation fix
            # (2026-04-26) lack the variant key — skip rather than
            # silently bucket them under "" and corrupt the drift
            # report.
            continue
        r_multiple = _coerce_float(record.get("outcome_r_multiple"))
        if r_multiple is None:
            continue
        entry_price = _coerce_float(record.get("entry_price"))
        fill_price = _coerce_float(record.get("fill_price"))
        slippage: float | None = None
        if entry_price is not None and fill_price is not None and entry_price != 0.0:
            slippage = (fill_price - entry_price) / entry_price
        pnl_f = _coerce_float(pnl)
        hit = pnl_f is not None and pnl_f > 0.0
        row: dict[str, Any] = {
            "variant": variant,
            "return": r_multiple,
            "hit": bool(hit),
        }
        if slippage is not None:
            row["slippage"] = slippage
        out.append(row)
    return out


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True))
                fh.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def main_drift_input(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Convert a live-incubation audit JSONL (with outcome_* stamps) "
            "into a drift-input JSONL (variant/return/slippage/hit)."
        )
    )
    p.add_argument("--audit-jsonl", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)

    rows = build_drift_input_from_audit(_read_jsonl(args.audit_jsonl))
    _write_jsonl(args.output, rows)
    print(f"wrote {args.output} ({len(rows)} rows)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Subcommand dispatcher used by ``python -m scripts.build_backtest_reference``.

    Subcommands:
      * ``backtest-reference`` — build the backtest_reference_<date>.json map.
      * ``drift-input`` — convert audit JSONL → drift-input JSONL.
    """
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "usage: python -m scripts.build_backtest_reference "
            "{backtest-reference|drift-input} [...]"
        )
        return 0
    sub = argv[0]
    rest = argv[1:]
    if sub in {"backtest-reference", "backtest_reference"}:
        return main_backtest_reference(rest)
    if sub in {"drift-input", "drift_input"}:
        return main_drift_input(rest)
    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (SIGINT/KeyboardInterrupt).")
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error in %s", __name__, exc_info=True)
        raise SystemExit(1) from None
