"""Config schema validation for open_prep weight sets and pipeline config.

Ported from IB_MON's config_validation.py — prevents silent misconfiguration.

Provides:
  validate_weights()     — sanity-checks scoring weight dicts
  validate_config()      — type-checks pipeline configuration values
  compute_config_diff()  — detect changes between two config snapshots
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected weight keys and sane ranges
# ---------------------------------------------------------------------------

EXPECTED_WEIGHT_KEYS: set[str] = {
    "gap",
    "gap_sector_relative",
    "rvol",
    "macro",
    "momentum_z",
    "hvb",
    "earnings_bmo",
    "news",
    "ext_hours",
    "analyst_catalyst",
    "vwap_distance",
    "freshness_decay",
    "institutional_quality",
    "estimate_revision",
    "liquidity_penalty",
    "corporate_action_penalty",
    "risk_off_penalty_multiplier",
    "ewma",
}

# Reasonable per-weight bounds: (min_inclusive, max_inclusive)
_WEIGHT_BOUNDS: dict[str, tuple[float, float]] = {
    "gap": (0.0, 5.0),
    "gap_sector_relative": (0.0, 3.0),
    "rvol": (0.0, 5.0),
    "macro": (0.0, 3.0),
    "momentum_z": (-2.0, 5.0),
    "hvb": (0.0, 3.0),
    "earnings_bmo": (0.0, 3.0),
    "news": (0.0, 5.0),
    "ext_hours": (0.0, 3.0),
    "analyst_catalyst": (0.0, 3.0),
    "vwap_distance": (-2.0, 3.0),
    "freshness_decay": (0.0, 3.0),
    "institutional_quality": (0.0, 3.0),
    "estimate_revision": (0.0, 3.0),
    "liquidity_penalty": (0.0, 5.0),
    "corporate_action_penalty": (0.0, 5.0),
    "risk_off_penalty_multiplier": (0.0, 5.0),
    "ewma": (0.0, 3.0),
}

# Total positive weight sum should be in this range
_POSITIVE_SUM_RANGE = (2.0, 30.0)


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------

def validate_weights(
    weights: dict[str, float],
    *,
    strict: bool = False,
) -> list[str]:
    """Validate a scoring weight dict.

    Parameters
    ----------
    weights : dict[str, float]
        Weight name → value mapping.
    strict : bool
        If True, raise ValueError on any issue; otherwise just return warnings.

    Returns
    -------
    list[str]
        List of warning/error messages (empty = all ok).
    """
    issues: list[str] = []

    # --- Missing keys ---
    missing = EXPECTED_WEIGHT_KEYS - set(weights.keys())
    if missing:
        issues.append(f"Missing weight keys: {sorted(missing)}")

    # --- Extra keys ---
    extra = set(weights.keys()) - EXPECTED_WEIGHT_KEYS
    if extra:
        issues.append(f"Unexpected weight keys (typo?): {sorted(extra)}")

    # --- Type checks ---
    for key, val in weights.items():
        if not isinstance(val, (int, float)):
            issues.append(f"Weight '{key}' has non-numeric value: {val!r}")
            continue

        # --- Bound checks ---
        bounds = _WEIGHT_BOUNDS.get(key)
        if bounds is not None:
            lo, hi = bounds
            if val < lo or val > hi:
                issues.append(
                    f"Weight '{key}' = {val:.4f} outside expected range [{lo}, {hi}]"
                )

    # --- Positive weight sum sanity ---
    positive_sum = sum(
        v for k, v in weights.items()
        if isinstance(v, (int, float))
        and k not in {"liquidity_penalty", "corporate_action_penalty", "risk_off_penalty_multiplier"}
        and v > 0
    )
    lo, hi = _POSITIVE_SUM_RANGE
    if positive_sum < lo or positive_sum > hi:
        issues.append(
            f"Total positive weight sum {positive_sum:.2f} outside expected range [{lo}, {hi}]"
        )

    # --- Log and optionally raise ---
    for msg in issues:
        logger.warning("Config validation: %s", msg)

    if strict and issues:
        raise ValueError(
            f"Weight validation failed with {len(issues)} issue(s):\n"
            + "\n".join(f"  • {m}" for m in issues)
        )

    return issues


# ---------------------------------------------------------------------------
# General config validation
# ---------------------------------------------------------------------------

_CONFIG_SCHEMA: dict[str, type | tuple[type, ...]] = {
    "top_n": (int,),
    "poll_interval": (int, float),
    "reload_interval": (int, float),
    "weight_label": (str,),
}


def validate_config(config: dict[str, Any]) -> list[str]:
    """Type-check pipeline configuration values.

    Returns list of warning messages (empty = all ok).
    """
    issues: list[str] = []
    for key, expected_types in _CONFIG_SCHEMA.items():
        if key not in config:
            continue
        val = config[key]
        if not isinstance(val, expected_types):
            issues.append(
                f"Config '{key}' should be {expected_types} but got {type(val).__name__}: {val!r}"
            )

    for msg in issues:
        logger.warning("Config validation: %s", msg)

    return issues


# ---------------------------------------------------------------------------
# Config diff
# ---------------------------------------------------------------------------

def compute_config_diff(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return a dict of changed keys: {key: {"old": ..., "new": ...}}.

    Only includes keys whose values differ. Useful for logging weight
    adjustments made by regime overlays.
    """
    diff: dict[str, dict[str, Any]] = {}
    all_keys = set(old) | set(new)
    for key in sorted(all_keys):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}
    return diff
