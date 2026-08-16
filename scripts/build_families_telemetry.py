"""C13/T5 — Producer for the C12 ``families[]`` telemetry contract.

Aggregates per-family Phase-B telemetry from the live drift-input and
audit JSONL streams into the strict five-key payload consumed by
:func:`scripts.emit_public_calibration_report._normalise_families`
and validated by :mod:`scripts.check_c12_trigger`.

Required C12 contract plus additive evidence truth:

    families[i] = {
        "name":              EventFamily,   # one of BOS|OB|FVG|SWEEP
        "live_days":         int >= 0,       # live-phase (live_small/live_full) days only
        "n_trades":          int >= 0,       # live-phase closed trades only
        "kill_switch_fires": int >= 0,
        "drift_verdict":     str,           # one of pass|acceptable|concerning|fail|...
        "evidence": {
            "MODELED_OOS": {"n_outcomes": int >= 0},
            "PAPER": {"days": int >= 0, "n_closed_outcomes": int >= 0},
            "LIVE": {"days": int >= 0, "n_closed_outcomes": int >= 0},
        },
        "coverage_status":  str,            # missing|partial|complete
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
* ``--variant-family-map <path>``: required JSON registry mapping each
  commercial ``variant`` string to its EventFamily and explicitly listing
  known non-family execution variants. The registry is the single source of
  truth — no heuristics and no fuzzy matching.
* ``--modeled-returns-json <glob>``: optional modeled-OOS returns-series
  artifact. These counts are labelled MODELED_OOS and never contribute to
  ``live_days`` or ``n_trades``.

Output is a JSON payload with two top-level keys:

    {
      "schema_version": "2.0.0",
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
# 2.1.0 (2026-08-16): additive commercial_claim per family row -- the
# operator's family-claim decision travels with the data it constrains.
FAMILIES_SCHEMA_VERSION = "2.1.0"

# The dated operator decision on which families the commercial story may
# claim (weekly review 2026-08-16: FVG leaves the four-family claim). The
# telemetry carries it so the public report renders the inequality instead
# of implying four equal families; tests/test_family_claim_status.py binds
# the "claimable" tier to the pre-registered minimum sample.
FAMILY_CLAIM_STATUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "commercial"
    / "family_claim_status.json"
)
_CLAIM_VOCABULARY = ("claimable", "evidence_building", "incubation")

# EventFamily literal pinned in smc_core/scoring.py:33. Kept as a
# tuple so test_event_family_alignment can grep both files.
EVENT_FAMILIES: tuple[str, ...] = ("BOS", "OB", "FVG", "SWEEP")

# Worst-case ordering for drift-verdict rollup. Lower index = better.
# Tracks _VERDICT_BANDS in scripts/compute_live_drift.py; unlisted newer verdicts rank unknown=5.
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

# Truth-audit F3 (2026-07-11): the C12 trigger's ``live_days`` / ``n_trades``
# must reflect a genuine Phase-B *live* track record, not Phase-A paper
# activity — that is the entire point of the gate (``check_c12_trigger``
# docstring: "externally sellable ... is Phase-B (live_small) not Phase-A
# (paper)"). Only records stamped with a live phase count toward those two
# metrics. Unknown / missing phase fails closed (does NOT count as live).
_LIVE_PHASES: frozenset[str] = frozenset({"live_small", "live_full"})
_PAPER_PHASES: frozenset[str] = frozenset({"paper"})


def _is_live_phase(rec: dict[str, Any]) -> bool:
    """Return ``True`` if ``rec`` was produced in a live (non-paper) phase."""
    phase = rec.get("phase")
    return isinstance(phase, str) and phase in _LIVE_PHASES


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
    paper_days: set[str] = field(default_factory=set)
    n_paper_outcomes: int = 0
    kill_switch_fires: int = 0
    drift_verdicts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BuildSummary:
    """Operator-readable counters for the run."""

    audit_files: int = 0
    drift_files: int = 0
    audit_records_total: int = 0
    audit_records_with_unknown_variant: int = 0
    audit_records_non_family: int = 0
    unknown_variants: set[str] = field(default_factory=set)
    non_family_variants: set[str] = field(default_factory=set)
    families_emitted: int = 0


@dataclass(frozen=True, slots=True)
class VariantRegistry:
    """Explicit commercial-family and non-family variant ownership."""

    family_variants: dict[str, str]
    non_family_variants: frozenset[str]


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


def load_variant_registry(path: Path) -> VariantRegistry:
    """Load a v2 variant registry or a legacy flat family map."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: variant→family map must be a JSON object",
        )
    if data.get("schema_version") == 2:
        family_data = data.get("family_variants")
        non_family_data = data.get("non_family_variants")
        if not isinstance(family_data, dict) or not isinstance(non_family_data, dict):
            raise ValueError(
                f"{path}: v2 registry requires object-valued family_variants "
                "and non_family_variants",
            )
    else:
        family_data = data
        non_family_data = {}

    out: dict[str, str] = {}
    for variant, family in family_data.items():
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
    non_family: set[str] = set()
    for variant, metadata in non_family_data.items():
        if not isinstance(variant, str) or not variant:
            raise ValueError(f"{path}: non-family keys must be non-empty strings")
        if variant in out:
            raise ValueError(f"{path}: variant {variant!r} has two ownership classes")
        if not isinstance(metadata, dict) or not metadata.get("scope"):
            raise ValueError(
                f"{path}: non-family variant {variant!r} requires scope metadata",
            )
        non_family.add(variant)
    return VariantRegistry(out, frozenset(non_family))


def load_variant_family_map(path: Path) -> dict[str, str]:
    """Compatibility view returning only commercial family variants."""
    return load_variant_registry(path).family_variants


def _resolve_glob(pattern: str) -> list[Path]:
    """Resolve a glob pattern to existing files, sorted for determinism."""
    matches = sorted(Path(p) for p in glob.glob(pattern))
    return [m for m in matches if m.is_file()]


def aggregate(
    *,
    audit_paths: Iterable[Path],
    drift_paths: Iterable[Path],
    variant_to_family: dict[str, str],
    non_family_variants: frozenset[str] = frozenset(),
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
                    variants_for_day = _variants_in_day(audit_path)
                    fam_for_day = {
                        variant_to_family.get(v) for v in variants_for_day
                    }
                    fam_for_day.discard(None)
                    if not fam_for_day:
                        if variants_for_day and variants_for_day.issubset(
                            non_family_variants
                        ):
                            # A known execution-only stream cannot contaminate
                            # commercial family risk evidence.
                            continue
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
                if variant in non_family_variants:
                    summary.audit_records_non_family += 1
                    summary.non_family_variants.add(variant)
                    continue
                summary.audit_records_with_unknown_variant += 1
                summary.unknown_variants.add(variant)
                continue

            acc = accs[family]
            # F3: live_days / n_trades are Phase-B live evidence — only
            # count live-phase records. Kill-switch fires are counted
            # regardless of phase (a paper-phase halt is still a real
            # risk event that must not be silently dropped).
            live_rec = _is_live_phase(rec)
            paper_rec = rec.get("phase") in _PAPER_PHASES
            if date_hint is not None and live_rec:
                acc.trade_days.add(date_hint)
            if date_hint is not None and paper_rec:
                acc.paper_days.add(date_hint)
            if _is_closed_trade(rec) and live_rec:
                acc.n_trades += 1
            elif _is_closed_trade(rec) and paper_rec:
                acc.n_paper_outcomes += 1
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
                if variant in non_family_variants:
                    summary.non_family_variants.add(variant)
                    continue
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


def load_family_claim_statuses(
    path: Path = FAMILY_CLAIM_STATUS_PATH,
) -> dict[str, str]:
    """Load the dated operator claim decision, fail-closed.

    Every family must be covered with a known vocabulary word -- a family
    missing here would otherwise render claim-less, which is exactly the
    silent-equality failure the record exists to prevent.
    """
    record = json.loads(path.read_text(encoding="utf-8"))
    families = record.get("families")
    if not isinstance(families, dict):
        raise ValueError(f"{path}: families must be an object")
    statuses: dict[str, str] = {}
    for family in EVENT_FAMILIES:
        entry = families.get(family)
        if not isinstance(entry, dict) or entry.get("status") not in _CLAIM_VOCABULARY:
            raise ValueError(
                f"{path}: families.{family}.status must be one of "
                f"{_CLAIM_VOCABULARY}"
            )
        statuses[family] = entry["status"]
    unknown = sorted(set(families) - set(EVENT_FAMILIES))
    if unknown:
        raise ValueError(f"{path}: unknown families {unknown}")
    return statuses


def to_strict_payload(
    accs: dict[str, _FamilyAccumulator],
    *,
    modeled_counts: dict[str, int] | None = None,
    claim_statuses: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert accumulators into C12 rows with explicit evidence classes."""
    modeled_counts = modeled_counts or {}
    if claim_statuses is None:
        claim_statuses = load_family_claim_statuses()
    payload: list[dict[str, Any]] = []
    for family in EVENT_FAMILIES:
        acc = accs.get(family, _FamilyAccumulator())
        evidence = {
            "MODELED_OOS": {"n_outcomes": int(modeled_counts.get(family, 0))},
            "PAPER": {
                "days": len(acc.paper_days),
                "n_closed_outcomes": int(acc.n_paper_outcomes),
            },
            "LIVE": {
                "days": len(acc.trade_days),
                "n_closed_outcomes": int(acc.n_trades),
            },
        }
        populated = sum(
            1
            for block in evidence.values()
            if any(int(value) > 0 for value in block.values())
        )
        payload.append({
            "name": family,
            "live_days": len(acc.trade_days),
            "n_trades": int(acc.n_trades),
            "kill_switch_fires": int(acc.kill_switch_fires),
            "drift_verdict": rollup_verdict(acc.drift_verdicts),
            "evidence": evidence,
            "coverage_status": (
                "complete" if populated == len(evidence)
                else "partial" if populated
                else "missing"
            ),
            "commercial_claim": claim_statuses[family],
        })
    return payload


def load_modeled_counts(pattern: str | None) -> dict[str, int]:
    """Load per-family counts from the newest modeled returns-series artifact."""
    if not pattern:
        return {}
    paths = _resolve_glob(pattern)
    if not paths:
        raise ValueError(f"no modeled returns artifact matched {pattern!r}")
    payload = json.loads(paths[-1].read_text(encoding="utf-8"))
    returns = payload.get("returns_by_variant") if isinstance(payload, dict) else None
    if not isinstance(returns, dict):
        raise ValueError(f"{paths[-1]}: missing object-valued returns_by_variant")
    counts: dict[str, int] = {}
    for family in EVENT_FAMILIES:
        values = returns.get(family, [])
        if not isinstance(values, list):
            raise ValueError(f"{paths[-1]}: returns_by_variant.{family} must be a list")
        counts[family] = len(values)
    return counts


def build_payload(
    *,
    audit_glob: str,
    drift_glob: str,
    variant_family_map: Path,
    modeled_returns_glob: str | None = None,
    summary: BuildSummary | None = None,
) -> dict[str, Any]:
    """End-to-end: globs + map → strict payload dict ready to write."""
    if summary is None:
        summary = BuildSummary()

    registry = load_variant_registry(variant_family_map)
    audit_paths = _resolve_glob(audit_glob)
    drift_paths = _resolve_glob(drift_glob)

    accs = aggregate(
        audit_paths=audit_paths,
        drift_paths=drift_paths,
        variant_to_family=registry.family_variants,
        non_family_variants=registry.non_family_variants,
        summary=summary,
    )
    families = to_strict_payload(
        accs,
        modeled_counts=load_modeled_counts(modeled_returns_glob),
    )
    summary.families_emitted = len(families)
    paper_ready = [
        row["name"]
        for row in families
        if row["evidence"]["PAPER"]["n_closed_outcomes"] > 0
    ]
    paper_missing = [family for family in EVENT_FAMILIES if family not in paper_ready]

    return {
        "schema_version": FAMILIES_SCHEMA_VERSION,
        "families": families,
        "phase1_paper_gate": {
            "status": "GREEN" if not paper_missing else "BLOCKED",
            "families_ready": paper_ready,
            "families_missing_closed_outcome": paper_missing,
        },
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
        "--modeled-returns-json",
        dest="modeled_returns_glob",
        help="Glob for modeled-OOS returns_series_*.json evidence.",
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
        modeled_returns_glob=args.modeled_returns_glob,
        summary=summary,
    )

    print(
        f"families_emitted={summary.families_emitted} "
        f"audit_files={summary.audit_files} "
        f"drift_files={summary.drift_files} "
        f"audit_records={summary.audit_records_total} "
        f"non_family_records={summary.audit_records_non_family} "
        f"unknown_variants={len(summary.unknown_variants)}",
    )
    if summary.unknown_variants:
        for v in sorted(summary.unknown_variants):
            print(f"  unknown_variant: {v}", file=sys.stderr)
        if args.strict_unknown_variants:
            return 2
    _atomic_write_json(args.output, payload)
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
