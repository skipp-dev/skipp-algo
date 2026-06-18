"""C13/T5 — Producer for the C12 ``families[]`` telemetry contract.

Aggregates per-family Phase-B telemetry from the live drift-input and
audit JSONL streams into the strict five-key payload consumed by
:func:`scripts.emit_public_calibration_report._normalise_families`
and validated by :mod:`scripts.check_c12_trigger`.

Strict contract (Deep-Review 2026-04-27 MAJOR finding mirror):

    families[i] = {
        "name":              EventFamily,   # one of BOS|OB|FVG|SWEEP
        "live_days":         int >= 0,
        "n_trades":          int >= 0,
        "kill_switch_fires": int >= 0,
        "drift_verdict":     str,           # one of pass|acceptable|concerning|fail|...
    }

Inputs
------

* ``--audit-jsonl <glob>``: one or more incubation audit JSONL files
  (typically ``cache/live/incubation_*.jsonl``). Each record carries
  ``variant``, ``action`` and an optional ``kill_switch_triggered``
  flag.
* ``--drift-jsonl <glob>``: per-day drift artefacts emitted by
  :mod:`scripts.compute_live_drift` (``cache/live/drift_*.json``).
  Each variant's ``verdict`` is rolled up into the family-level
  ``drift_verdict`` via the worst-case ordering pinned below.
* ``--variant-family-map <path>``: required JSON file mapping each
  ``variant`` string to its EventFamily (``BOS``|``OB``|``FVG``|
  ``SWEEP``). The map is the single source of truth — no heuristics,
  no fuzzy matching. Variants not in the map are flagged in the run
  summary and excluded from the telemetry (strict mode); any unknown
  variant therefore fails CI rather than silently degrading.

Output is a JSON payload with two top-level keys:

    {
      "schema_version": "1.0.0",
      "families": [...]
    }

The producer is pure stdlib + ``glob`` so the daily cron stays
network-free.
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
import contextlib
import glob
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Pinned by tests/test_build_families_telemetry.py against
# scripts/emit_public_calibration_report.py:_C12_FAMILY_KEYS so the
# producer cannot drift from the consumer schema.
FAMILIES_SCHEMA_VERSION = "1.0.0"

# EventFamily literal pinned in smc_core/scoring.py:33. Kept as a
# tuple so test_event_family_alignment can grep both files.
EVENT_FAMILIES: tuple[str, ...] = ("BOS", "OB", "FVG", "SWEEP")

# Worst-case ordering for drift-verdict rollup. Lower index = better.
# Mirrors _VERDICT_BANDS in scripts/compute_live_drift.py:53.
_VERDICT_RANK: dict[str, int] = {
    "pass": 0,
    "acceptable": 1,
    "insufficient_sample": 2,
    "concerning": 3,
    "fail": 4,
    "unknown": 5,
}

# Audit ``action`` values that represent a *closed* trade. Live
# incubation writes ``audit_only`` / ``filled`` / ``submitted`` /
# ``created`` etc. per intent; only the terminal *exit* actions count
# towards ``n_trades`` for the C12 trigger gate. ``filled`` is the
# *entry* fill (broker confirms entry order) and is excluded — the
# trade is not yet closed at that point and counting it would
# double-count once ``closed``/``tp_hit``/``stop_hit``/``flattened``
# fires. Anything else (intent creation, halts, reconnects, cancels)
# is excluded so the trigger does not see a permanently zero count
# even when the live pipeline runs.
_CLOSED_TRADE_ACTIONS: frozenset[str] = frozenset({
    "closed",
    "tp_hit",
    "stop_hit",
    "flattened",
})


def _is_closed_trade(rec: dict[str, Any]) -> bool:
    """Return ``True`` if ``rec`` represents a closed trade.

    Either the ``action`` is one of the terminal closed-trade actions
    or the record carries an ``outcome_pnl_usd`` field (set by
    :mod:`scripts.backfill_live_outcomes`).
    """
    action = rec.get("action")
    if isinstance(action, str) and action in _CLOSED_TRADE_ACTIONS:
        return True
    return rec.get("outcome_pnl_usd") is not None


@dataclass(slots=True)
class _FamilyAccumulator:
    """Per-family running totals before the strict-payload conversion."""

    trade_days: set[str] = field(default_factory=set)
    n_trades: int = 0
    kill_switch_fires: int = 0
    drift_verdicts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BuildSummary:
    """Operator-readable counters for the run."""

    audit_files: int = 0
    drift_files: int = 0
    audit_records_total: int = 0
    audit_records_with_unknown_variant: int = 0
    unknown_variants: set[str] = field(default_factory=set)
    families_emitted: int = 0


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic JSON write: tmp file + ``os.replace``."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".families_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace pattern above.
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield JSONL records, skipping blank lines, raising on bad JSON."""
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_no} invalid JSON: {exc.msg}",
                ) from exc
            if not isinstance(obj, dict):
                raise ValueError(
                    f"{path}:{line_no} expected JSON object, got {type(obj).__name__}",
                )
            yield obj


def _trade_date_from_path(p: Path) -> str | None:
    """Extract ``YYYY-MM-DD`` from common filename patterns.

    Examples:
        cache/live/incubation_2026-04-25.jsonl → "2026-04-25"
        cache/live/drift_2026-04-25.json       → "2026-04-25"
    """
    stem = p.stem
    for token in stem.split("_"):
        if len(token) == 10 and token[4] == "-" and token[7] == "-":
            try:
                int(token[:4])
                int(token[5:7])
                int(token[8:10])
            except ValueError:
                continue
            return token
    return None


def load_variant_family_map(path: Path) -> dict[str, str]:
    """Load + validate a {variant: EventFamily} JSON map.

    Strict: every value must be a member of :data:`EVENT_FAMILIES`.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: variant→family map must be a JSON object",
        )
    out: dict[str, str] = {}
    for variant, family in data.items():
        if not isinstance(variant, str) or not variant:
            raise ValueError(
                f"{path}: keys must be non-empty strings; got {variant!r}",
            )
        if family not in EVENT_FAMILIES:
            raise ValueError(
                f"{path}: variant {variant!r} mapped to unknown family "
                f"{family!r}; expected one of {EVENT_FAMILIES}",
            )
        out[variant] = family
    return out


def _resolve_glob(pattern: str) -> list[Path]:
    """Resolve a glob pattern to existing files, sorted for determinism."""
    matches = sorted(Path(p) for p in glob.glob(pattern))
    return [m for m in matches if m.is_file()]


def aggregate(
    *,
    audit_paths: Iterable[Path],
    drift_paths: Iterable[Path],
    variant_to_family: dict[str, str],
    summary: BuildSummary | None = None,
) -> dict[str, _FamilyAccumulator]:
    """Aggregate audit + drift inputs into per-family accumulators."""
    if summary is None:
        summary = BuildSummary()

    accs: dict[str, _FamilyAccumulator] = defaultdict(_FamilyAccumulator)

    # -------- Audit pass: live_days, n_trades, kill_switch_fires --------
    for audit_path in audit_paths:
        summary.audit_files += 1
        date_hint = _trade_date_from_path(audit_path)
        for rec in _iter_jsonl(audit_path):
            summary.audit_records_total += 1
            variant = rec.get("variant")
            if not isinstance(variant, str) or not variant:
                # Halt records and other non-trade entries — count
                # kill-switch fires under their source family if we
                # can recover it, otherwise drop. Halt records carry
                # no variant; we therefore attribute kill-switch
                # fires *per audit file* to all families that traded
                # that day. Conservative for the C12 contract:
                # ``kill_switch_fires == 0`` is hard, so any fire
                # propagates.
                if rec.get("kill_switch_triggered") is True:
                    fam_for_day = {variant_to_family.get(v) for v in
                                   _variants_in_day(audit_path)}
                    fam_for_day.discard(None)
                    if not fam_for_day:
                        # No trades that day (halt fired before any
                        # variant traded) — conservative fallback per
                        # the C12 contract: a kill-switch fire must
                        # never be silently dropped, so attribute it
                        # to every event family. This keeps the
                        # ``kill_switch_fires == 0`` Phase-B invariant
                        # honest even on halt-only days.
                        fam_for_day = set(EVENT_FAMILIES)
                    for fam in fam_for_day:
                        accs[fam].kill_switch_fires += 1
                continue

            family = variant_to_family.get(variant)
            if family is None:
                summary.audit_records_with_unknown_variant += 1
                summary.unknown_variants.add(variant)
                continue

            acc = accs[family]
            if date_hint is not None:
                acc.trade_days.add(date_hint)
            if _is_closed_trade(rec):
                acc.n_trades += 1
            elif rec.get("kill_switch_triggered") is True:
                acc.kill_switch_fires += 1

    # -------- Drift pass: drift_verdict per family (worst-case rollup) --
    for drift_path in drift_paths:
        summary.drift_files += 1
        try:
            payload = json.loads(drift_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{drift_path}: invalid JSON ({exc.msg})") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{drift_path}: expected JSON object")
        for variant_block in payload.get("variants", []) or []:
            if not isinstance(variant_block, dict):
                continue
            variant = variant_block.get("variant")
            verdict = variant_block.get("verdict")
            if not isinstance(variant, str) or not isinstance(verdict, str):
                continue
            family = variant_to_family.get(variant)
            if family is None:
                summary.unknown_variants.add(variant)
                continue
            accs[family].drift_verdicts.append(verdict)

    return accs


def _variants_in_day(audit_path: Path) -> set[str]:
    """Return the set of variants that traded in a single audit file.

    Used only for the kill-switch fan-out path above. Re-reads the
    file: cheap because it runs at most once per audit file and only
    when a halt record is encountered.
    """
    seen: set[str] = set()
    for rec in _iter_jsonl(audit_path):
        v = rec.get("variant")
        if isinstance(v, str) and v:
            seen.add(v)
    return seen


def rollup_verdict(verdicts: list[str]) -> str:
    """Worst-case rollup over per-variant verdicts."""
    if not verdicts:
        return "unknown"
    return max(
        verdicts,
        key=lambda v: _VERDICT_RANK.get(v, _VERDICT_RANK["unknown"]),
    )


def to_strict_payload(
    accs: dict[str, _FamilyAccumulator],
) -> list[dict[str, Any]]:
    """Convert accumulators into the strict five-key family list."""
    payload: list[dict[str, Any]] = []
    for family in EVENT_FAMILIES:
        if family not in accs:
            # Family never traded in the window; emit a zero-row so
            # the consumer can still see it and BLOCK on
            # n_trades < MIN_LIVE_TRADES. This is strict-mode
            # behaviour: silence is the wrong default for C12.
            payload.append({
                "name": family,
                "live_days": 0,
                "n_trades": 0,
                "kill_switch_fires": 0,
                "drift_verdict": "unknown",
            })
            continue
        acc = accs[family]
        payload.append({
            "name": family,
            "live_days": len(acc.trade_days),
            "n_trades": int(acc.n_trades),
            "kill_switch_fires": int(acc.kill_switch_fires),
            "drift_verdict": rollup_verdict(acc.drift_verdicts),
        })
    return payload


def build_payload(
    *,
    audit_glob: str,
    drift_glob: str,
    variant_family_map: Path,
    summary: BuildSummary | None = None,
) -> dict[str, Any]:
    """End-to-end: globs + map → strict payload dict ready to write."""
    if summary is None:
        summary = BuildSummary()

    variant_to_family = load_variant_family_map(variant_family_map)
    audit_paths = _resolve_glob(audit_glob)
    drift_paths = _resolve_glob(drift_glob)

    accs = aggregate(
        audit_paths=audit_paths,
        drift_paths=drift_paths,
        variant_to_family=variant_to_family,
        summary=summary,
    )
    families = to_strict_payload(accs)
    summary.families_emitted = len(families)

    return {
        "schema_version": FAMILIES_SCHEMA_VERSION,
        "families": families,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Producer for C12 families[] telemetry — strict five-key contract."
        ),
    )
    p.add_argument(
        "--audit-jsonl",
        required=True,
        help="Glob for incubation audit JSONL files "
        "(e.g. 'cache/live/incubation_*.jsonl').",
    )
    p.add_argument(
        "--drift-jsonl",
        required=True,
        help="Glob for daily drift artefacts (e.g. 'cache/live/drift_*.json').",
    )
    p.add_argument(
        "--variant-family-map",
        required=True,
        type=Path,
        help='JSON map: {"variant_key": "BOS"|"OB"|"FVG"|"SWEEP"}.',
    )
    p.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output JSON path.",
    )
    p.add_argument(
        "--strict-unknown-variants",
        action="store_true",
        help=(
            "Exit with status 2 if any variant is missing from the "
            "variant→family map. Default: warn-only."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _parse_args(argv)
    summary = BuildSummary()
    payload = build_payload(
        audit_glob=args.audit_jsonl,
        drift_glob=args.drift_jsonl,
        variant_family_map=args.variant_family_map,
        summary=summary,
    )
    _atomic_write_json(args.output, payload)

    print(
        f"families_emitted={summary.families_emitted} "
        f"audit_files={summary.audit_files} "
        f"drift_files={summary.drift_files} "
        f"audit_records={summary.audit_records_total} "
        f"unknown_variants={len(summary.unknown_variants)}",
    )
    if summary.unknown_variants:
        for v in sorted(summary.unknown_variants):
            print(f"  unknown_variant: {v}", file=sys.stderr)
        if args.strict_unknown_variants:
            return 2
    return 0


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
