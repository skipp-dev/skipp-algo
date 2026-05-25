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

Output shape (``REPORT_SCHEMA_VERSION = 1``)::

    {
      "schema_version": 1,
      "gate_schema_version": <DECISION_SCHEMA_VERSION>,
      "generated_at": "<ISO-8601 UTC, sortable>",
      "strict_provenance": true,
      "decisions": [<Decision>, ...]
    }

Exit codes
----------
0 : all families promoted (and the report was written).
1 : configuration error (bad input file, unknown family, etc.).
2 : at least one family blocked. Useful as a CI signal so the wrapping
    workflow can branch on the rolling-benchmark result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_args

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


def build_report(
    snapshots: list[FamilyMetrics],
    *,
    strict_provenance: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the gate on every snapshot and assemble the report dict."""
    thresholds = GateThresholds(strict_provenance=strict_provenance)
    gate = PromotionGate(thresholds)
    decisions: list[Decision] = [gate.evaluate(snap) for snap in snapshots]
    ts = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "gate_schema_version": DECISION_SCHEMA_VERSION,
        "generated_at": ts,
        "strict_provenance": bool(strict_provenance),
        "decisions": [dict(d) for d in decisions],
    }


def _report_exit_code(report: dict[str, Any]) -> int:
    if all(d["promoted"] for d in report["decisions"]):
        return 0
    return 2


def _archive_stamp(generated_at: str) -> str:
    """Filename-safe UTC stamp derived from the report's generated_at field."""
    # Strip timezone offset / fractional seconds, then drop punctuation so the
    # name sorts lexicographically (e.g. 20260525T123456Z).
    cleaned = generated_at.split("+", 1)[0].split(".", 1)[0]
    return cleaned.replace("-", "").replace(":", "") + "Z"


def _archive_report(
    report: dict[str, Any], archive_dir: str | os.PathLike[str] | None
) -> Path | None:
    """Write a timestamped copy of *report* to *archive_dir*, if configured."""
    if archive_dir is None or str(archive_dir).strip() == "":
        return None
    target_dir = Path(archive_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _archive_stamp(str(report["generated_at"]))
    archive_path = target_dir / f"promotion_decisions_{stamp}.json"
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
    args = parser.parse_args(argv)

    if not args.metrics.exists():
        print(f"ERROR: metrics file does not exist: {args.metrics}", file=sys.stderr)
        return 1

    try:
        snapshots = _load_bundle(args.metrics)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"ERROR: failed to load metrics bundle {args.metrics}: {exc}", file=sys.stderr)
        return 1

    report = build_report(snapshots, strict_provenance=not args.no_strict)
    atomic_write_json(report, args.output, indent=2, sort_keys=False)
    archive_path = _archive_report(report, args.archive_dir)
    if archive_path is not None:
        print(f"archived: {archive_path}", file=sys.stderr)
    print(json.dumps(report, indent=2))
    return _report_exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
