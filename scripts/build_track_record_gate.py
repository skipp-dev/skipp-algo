"""C6/C7 — Producer for ``cache/calibration/track_record_gate_<date>.json``.

Reads per-trade returns (per-variant if available) and writes the
verdict dict consumed by :func:`scripts.build_dashboard_payload._gate_status_from_track_record`
and :func:`scripts.build_dashboard_payload._per_variant_gate_status`.

Without this file the dashboard renders ``gate_status="unknown"`` on
every row.

Pure stdlib + numpy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.track_record_gate import (
    evaluate_track_record_gate,
    evaluate_track_record_gate_per_variant,
    verdict_to_dict,
)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace pattern above.
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            # C-sprint deep-review: flush+fsync before os.replace so a
            # crash between buffer-write and disk-sync does not leave
            # a truncated/empty gate verdict (consumed by the
            # dashboard payload aggregator and the public report).
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _load_returns_payload(path: Path) -> dict[str, Any]:
    """Load a returns file with one of two shapes.

    Shape A (global): ``{"returns": [r1, r2, ...]}``.
    Shape B (per-variant): ``{"returns_by_variant": {variant: [...]}}``.
    Either shape may also carry an optional ``rr_target`` scalar and
    optional per-variant scalars (WFE / permutation_p / fdr_rate /
    per_regime_hit_rate_spread) which are forwarded to the gate.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object at top level")
    return raw


def _safe_float(value: Any, default: float) -> float:
    """Coerce ``value`` to ``float`` only if it is a real number-like.

    Returns ``default`` for ``None`` or anything that does not cast
    cleanly. The cron-retried producer must not crash when the input
    JSON carries an explicit ``"rr_target": null``.
    """

    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_scalar(value: Any) -> float | None:
    """Coerce to ``float`` or return ``None`` for any non-scalar input."""

    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int; reject silently to avoid passing
        # True/False as a metric value.
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_by_variant(value: Any) -> dict[str, float] | None:
    """Coerce to ``{variant: float}`` mapping; drop wrong-typed values.

    A non-mapping (list, string, ...) becomes ``None`` so the gate
    treats it as "metric not available" rather than truthy garbage.
    """

    if not isinstance(value, Mapping):
        return None
    out: dict[str, float] = {}
    for k, v in value.items():
        scalar = _safe_optional_scalar(v)
        if scalar is not None:
            out[str(k)] = scalar
    return out or None


def build_track_record_gate_payload(returns_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the verdict dict (global + optional per-variant block)."""

    rr_target = _safe_float(returns_payload.get("rr_target"), 1.0)
    # Stat-review S4 (#2674): optional observed trade frequency; when the
    # producer supplies it, the Sharpe annualisation uses the trade clock
    # instead of the daily-bar default (see evaluate_track_record_gate).
    trades_per_year = _safe_optional_scalar(returns_payload.get("trades_per_year"))
    wfe_global = _safe_optional_scalar(returns_payload.get("walk_forward_efficiency"))
    perm_p_global = _safe_optional_scalar(returns_payload.get("permutation_p"))
    fdr_global = _safe_optional_scalar(returns_payload.get("fdr_rate"))
    spread_global = _safe_optional_scalar(
        returns_payload.get("per_regime_hit_rate_spread")
    )

    returns_by_variant_raw = returns_payload.get("returns_by_variant")
    if isinstance(returns_by_variant_raw, dict) and returns_by_variant_raw:
        returns_by_variant = {
            str(k): list(v)
            for k, v in returns_by_variant_raw.items()
            if isinstance(v, list)
        }
        # Concatenate every variant for the global verdict; per-variant
        # block carries the per-row verdicts the dashboard renders.
        all_returns = [r for rs in returns_by_variant.values() for r in rs]
        global_verdict = evaluate_track_record_gate(
            all_returns,
            rr_target=rr_target,
            walk_forward_efficiency=wfe_global,
            permutation_p=perm_p_global,
            fdr_rate=fdr_global,
            per_regime_hit_rate_spread=spread_global,
            trades_per_year=trades_per_year,
        )
        per_variant = evaluate_track_record_gate_per_variant(
            returns_by_variant,
            rr_target=rr_target,
            trades_per_year=trades_per_year,
            walk_forward_efficiency_by_variant=_safe_by_variant(
                returns_payload.get("walk_forward_efficiency_by_variant")
            ),
            permutation_p_by_variant=_safe_by_variant(
                returns_payload.get("permutation_p_by_variant")
            ),
            fdr_rate_by_variant=_safe_by_variant(
                returns_payload.get("fdr_rate_by_variant")
            ),
            per_regime_hit_rate_spread_by_variant=_safe_by_variant(
                returns_payload.get("per_regime_hit_rate_spread_by_variant")
            ),
        )
        out = verdict_to_dict(global_verdict)
        out["per_variant"] = per_variant
        return out

    returns = returns_payload.get("returns") or []
    if not isinstance(returns, list):
        raise ValueError("returns must be a list of floats")
    verdict = evaluate_track_record_gate(
        returns,
        rr_target=rr_target,
        walk_forward_efficiency=wfe_global,
        permutation_p=perm_p_global,
        fdr_rate=fdr_global,
        per_regime_hit_rate_spread=spread_global,
        trades_per_year=trades_per_year,
    )
    return verdict_to_dict(verdict)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Compute the track-record-gate verdict and write "
            "cache/calibration/track_record_gate_<date>.json."
        )
    )
    p.add_argument(
        "--returns",
        type=Path,
        required=True,
        help='JSON with {"returns": [...]} or {"returns_by_variant": {...}}.',
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)

    returns_payload = _load_returns_payload(args.returns)
    payload = build_track_record_gate_payload(returns_payload)
    _atomic_write_json(args.output, payload)
    n_var = len(payload.get("per_variant", {}))
    print(
        f"wrote {args.output} (status={payload['status']}, "
        f"per_variant={n_var})"
    )
    return 0


__all__ = [
    "build_track_record_gate_payload",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
