"""Sprint W1.b — production CLI for the X2 PromotionGate.

Reads a per-family metrics bundle (assembled upstream by the C-sprint
artifacts: walk-forward, BCa bootstrap, block-permutation, PSR/MinIS,
PSI-trend, conformal calibration) and emits a single Decision bundle
report. This is the runtime hook that turns the X2 consolidator from
a tests-only artifact into a real promotion-decision producer.

The bundle file is a JSON list of ``FamilyMetrics``-shaped dicts; one
entry per ``EventFamily``. The CLI runs ``PromotionGate.evaluate(...)``
in strict mode by default (``--no-strict`` disables) and writes the
report to ``artifacts/promotion_decisions.json`` unless ``--output``
overrides it.

Output shape (``REPORT_SCHEMA_VERSION = 2``)::

    {
      "schema_version": 2,
      "gate_schema_version": <DECISION_SCHEMA_VERSION>,
      "generated_at": "<ISO-8601 UTC, sortable>",
      "strict_provenance": true,
      "decisions": [<Decision>, ...],
      "context": {<symbol/dataset/schema/window>, ...}  # optional, omitted when absent
    }

Exit codes
----------
0 : all families promoted (and the report was written).
1 : configuration error (bad input file, unknown family, etc.) OR
    --strict-universe pre-flight failed (no snapshot for the requested
    trade date, #2352).
2 : at least one family blocked. Useful as a CI signal so the wrapping
    workflow can branch on the rolling-benchmark result.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, get_args

from databento_universe import (
    MissingUniverseSnapshotError,
    load_universe_for_backtest,
)
from governance.magnitude_stage_policy import (
    DEFAULT_POLICY_PATH,
    MagnitudeStagePolicy,
    load_policy,
)
from governance.promotion_gate import (
    DECISION_SCHEMA_VERSION,
    FamilyMetrics,
    GateThresholds,
    PromotionGate,
)
from governance.promotion_report import (
    DEFAULT_PROMOTION_DECISIONS_PATH,
    REPORT_SCHEMA_VERSION,
)
from governance.types import Decision, EventFamily
from scripts.magnitude_snapshot_wiring import (
    apply_to_family_metrics,
    load_magnitude_snapshots,
)
from scripts.run_magnitude_shadow_ledger import DEFAULT_LEDGER
from scripts.smc_atomic_write import atomic_write_json

_VALID_FAMILIES = set(get_args(EventFamily))

# PQ Re-Audit A8 (#2354): every gate run also archives a timestamped copy
# of the report here so the weekly dashboard has a real history to aggregate.
# Pass --archive-dir '' to opt out (legacy single-file behaviour).
DEFAULT_PROMOTION_DECISIONS_ARCHIVE_DIR = Path("governance") / "promotion_decisions"

# Numeric / bool FamilyMetrics fields accepted in the bundle JSON.
# ``family``, ``provenance`` and ``extras`` are handled separately.
_NUMERIC_FIELDS = (
    "brier",
    "brier_ci_upper",
    "ece",
    "fdr_pvalue",
    "psr",
    "mintrl_years",
    "psi",
    "live_brier",
    "walkforward_brier",
    "psi_slope",
    "conformal_coverage",
    "conformal_target",
    # ADR-0023: optional move-size resolution AUC carried alongside the
    # additive ``magnitude_resolution_pass`` flag (both default-absent => dormant).
    "magnitude_auc",
)


def _family_metrics_from_dict(payload: dict[str, Any]) -> FamilyMetrics:
    family = payload.get("family")
    if family not in _VALID_FAMILIES:
        raise ValueError(
            f"unknown or missing 'family' in metrics entry: {family!r}; "
            f"expected one of {sorted(_VALID_FAMILIES)}"
        )
    kwargs: dict[str, Any] = {"family": family}
    for key in _NUMERIC_FIELDS:
        if key in payload and payload[key] is not None:
            kwargs[key] = float(payload[key])
    if "regime_degraded" in payload and payload["regime_degraded"] is not None:
        kwargs["regime_degraded"] = bool(payload["regime_degraded"])
    if (
        "magnitude_resolution_pass" in payload
        and payload["magnitude_resolution_pass"] is not None
    ):
        kwargs["magnitude_resolution_pass"] = bool(payload["magnitude_resolution_pass"])
    if "provenance" in payload and payload["provenance"] is not None:
        prov = payload["provenance"]
        if not isinstance(prov, dict):
            raise ValueError(f"'provenance' for family {family!r} must be a dict")
        kwargs["provenance"] = dict(prov)
    if "extras" in payload and payload["extras"] is not None:
        extras = payload["extras"]
        if not isinstance(extras, dict):
            raise ValueError(f"'extras' for family {family!r} must be a dict")
        kwargs["extras"] = {k: float(v) for k, v in extras.items()}
    return FamilyMetrics(**kwargs)


def _load_bundle(path: Path) -> list[FamilyMetrics]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"metrics bundle {path} must be a JSON list, got {type(raw).__name__}"
        )
    snapshots = [_family_metrics_from_dict(item) for item in raw]
    seen: set[str] = set()
    for snap in snapshots:
        if snap.family in seen:
            raise ValueError(f"duplicate family {snap.family!r} in bundle {path}")
        seen.add(snap.family)
    return snapshots


def apply_magnitude_feed(
    snapshots: list[FamilyMetrics],
    *,
    policy: MagnitudeStagePolicy,
    ledger_path: str = DEFAULT_LEDGER,
) -> list[FamilyMetrics]:
    """Inject the latest shadow-ledger move-size verdicts (ADR-0023 Stage 2).

    Only families in ``policy.armed_families`` receive a verdict — the FVG/OB
    control families FAIL the §2 bar by design and must never have that
    ``False`` fed into a gate they are not a promotion target of. A bundle
    entry that already carries an explicit ``magnitude_resolution_pass`` wins
    over the ledger (the upstream producer is closer to the data). A missing
    or empty ledger is fail-soft: the snapshot stays unmeasured and the armed
    family is blocked by the fail-closed Stage-2 info blocker instead.
    """
    if not policy.armed_families:
        return snapshots
    ledger_snaps = load_magnitude_snapshots(ledger_path)
    out: list[FamilyMetrics] = []
    for snap in snapshots:
        ledger_snap = ledger_snaps.get(snap.family)
        if (
            snap.family in policy.armed_families
            and snap.magnitude_resolution_pass is None
            and ledger_snap is not None
        ):
            out.append(apply_to_family_metrics(snap, ledger_snap))
        else:
            out.append(snap)
    return out


def build_report(
    snapshots: list[FamilyMetrics],
    *,
    strict_provenance: bool = True,
    now: datetime | None = None,
    context: Mapping[str, Any] | None = None,
    magnitude_strict_families: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Run the gate on every snapshot and assemble the report dict.

    ``context`` (optional) records the run's data provenance — symbol,
    dataset, schema, timeframe, window — so per-symbol archives written by the
    edge pipeline are self-describing and a multi-symbol dashboard scan can
    filter heterogeneous runs apart. Omitted entirely on context-less runs so
    the loader contract is unchanged (schema_version 2).

    ``magnitude_strict_families`` arms the ADR-0023 Stage-2 fail-closed
    posture for the listed families only (see ``GateThresholds``); it has no
    effect on any other check.
    """
    thresholds = GateThresholds(
        strict_provenance=strict_provenance,
        magnitude_strict_families=magnitude_strict_families,
    )
    gate = PromotionGate(thresholds)
    decisions: list[Decision] = [gate.evaluate(snap) for snap in snapshots]
    ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "gate_schema_version": DECISION_SCHEMA_VERSION,
        "generated_at": ts,
        "strict_provenance": bool(strict_provenance),
        "decisions": [dict(d) for d in decisions],
    }
    if context is not None:
        report["context"] = dict(context)
    return report


def _report_exit_code(report: dict[str, Any]) -> int:
    if all(d["promoted"] for d in report["decisions"]):
        return 0
    return 2


def _archive_stamp(generated_at: str) -> str:
    """Filename-safe UTC stamp derived from the report's generated_at field."""
    # Strip timezone offset / fractional seconds and any trailing 'Z', then
    # drop punctuation so the name sorts lexicographically (e.g.
    # 20260525T123456Z) without producing a double-Z for ISO inputs that
    # already end in 'Z'.
    cleaned = generated_at.split("+", 1)[0].split(".", 1)[0].rstrip("Z")
    return cleaned.replace("-", "").replace(":", "") + "Z"


def _label_slug(label: str | None) -> str:
    """Filename-safe slug from an archive label (e.g. a symbol).

    Keeps ``[A-Za-z0-9]`` only, uppercases, and caps length so the archive
    filename stays portable across filesystems. Returns ``""`` when nothing
    usable remains (caller then falls back to the unlabelled filename).
    """
    if not label:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(label)).upper()[:24]


def _archive_report(
    report: dict[str, Any],
    archive_dir: str | os.PathLike[str] | None,
    *,
    label: str | None = None,
) -> Path | None:
    """Write a timestamped copy of *report* to *archive_dir*, if configured.

    When *label* (e.g. the symbol) is supplied it is slugged into the filename
    — ``promotion_decisions_<LABEL>_<stamp>.json`` — so per-symbol runs written
    in the same second don't overwrite each other and the archive is auditable
    by name alone. The ``promotion_decisions_*.json`` glob every consumer uses
    still matches.
    """
    if archive_dir is None or str(archive_dir).strip() == "":
        return None
    target_dir = Path(archive_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _archive_stamp(str(report["generated_at"]))
    slug = _label_slug(label)
    name = (
        f"promotion_decisions_{slug}_{stamp}.json"
        if slug
        else f"promotion_decisions_{stamp}.json"
    )
    archive_path = target_dir / name
    atomic_write_json(report, archive_path, indent=2, sort_keys=False)
    return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sprint W1.b: run the X2 PromotionGate over a family bundle."
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        required=True,
        help="Path to a JSON list of FamilyMetrics-shaped dicts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PROMOTION_DECISIONS_PATH,
        help=(
            "Path to write the promotion-gate report JSON "
            f"(default: {DEFAULT_PROMOTION_DECISIONS_PATH.as_posix()})."
        ),
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Disable strict_provenance (legacy behaviour; do not use in prod).",
    )
    parser.add_argument(
        "--archive-dir",
        type=str,
        default=str(DEFAULT_PROMOTION_DECISIONS_ARCHIVE_DIR),
        help=(
            "Directory the timestamped report copy is written into for the "
            "weekly dashboard (#2354). Pass '' to disable."
        ),
    )
    parser.add_argument(
        "--universe-trade-date",
        type=date.fromisoformat,
        default=None,
        help=(
            "ISO trade date (YYYY-MM-DD) to validate against the per-day "
            "universe snapshot store before running the gate (#2352)."
        ),
    )
    parser.add_argument(
        "--strict-universe",
        action="store_true",
        help=(
            "Pre-flight: require a persisted universe snapshot for "
            "--universe-trade-date. Exits with code 1 if absent (#2352)."
        ),
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=None,
        help="Override the universe snapshot root directory (#2352).",
    )
    parser.add_argument(
        "--magnitude-policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help=(
            "ADR-0023 stage policy JSON naming the Stage-2-armed families "
            f"(default: {DEFAULT_POLICY_PATH.as_posix()}; missing => unarmed)."
        ),
    )
    parser.add_argument(
        "--magnitude-ledger",
        type=str,
        default=DEFAULT_LEDGER,
        help=(
            "Move-size shadow ledger JSONL feeding armed families' "
            f"magnitude verdicts (default: {DEFAULT_LEDGER}; missing => "
            "fail-soft, armed families stay unmeasured/blocked)."
        ),
    )
    parser.add_argument(
        "--no-magnitude-feed",
        action="store_true",
        help=(
            "Disable the ADR-0023 ledger feed AND per-family arming "
            "(diagnostic escape hatch; gate falls back to the bundle alone)."
        ),
    )
    args = parser.parse_args(argv)

    if args.strict_universe and args.universe_trade_date is None:
        print(
            "ERROR: --strict-universe requires --universe-trade-date (#2352)",
            file=sys.stderr,
        )
        return 1
    if args.universe_trade_date is not None:
        try:
            load_universe_for_backtest(
                args.universe_trade_date,
                strict=args.strict_universe,
                snapshot_root=args.snapshot_root,
            )
        except MissingUniverseSnapshotError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if not args.metrics.exists():
        print(f"ERROR: metrics file does not exist: {args.metrics}", file=sys.stderr)
        return 1

    try:
        snapshots = _load_bundle(args.metrics)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"ERROR: failed to load metrics bundle {args.metrics}: {exc}", file=sys.stderr)
        return 1

    if args.no_magnitude_feed:
        policy = MagnitudeStagePolicy()
    else:
        try:
            policy = load_policy(args.magnitude_policy)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        try:
            snapshots = apply_magnitude_feed(
                snapshots, policy=policy, ledger_path=args.magnitude_ledger
            )
        except ValueError as exc:
            # W7-1: corrupt shadow ledger — fail closed (rc 1) rather than
            # gate armed families on whatever rows happened to survive.
            print(f"ERROR: magnitude shadow ledger: {exc}", file=sys.stderr)
            return 1
        if policy.armed_families:
            print(
                "ADR-0023 Stage 2 armed (magnitude strict): "
                + ", ".join(sorted(policy.armed_families)),
                file=sys.stderr,
            )

    report = build_report(
        snapshots,
        strict_provenance=not args.no_strict,
        magnitude_strict_families=policy.armed_families,
    )
    atomic_write_json(report, args.output, indent=2, sort_keys=False)
    archive_path = _archive_report(report, args.archive_dir)
    if archive_path is not None:
        print(f"archived: {archive_path}", file=sys.stderr)
    print(json.dumps(report, indent=2))
    return _report_exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
