"""Regression: `score_candidate` component-cap single-pass projection.

`open_prep.scorer.score_candidate` caps each *positive* score component to
``SCORE_COMPONENT_CAP_FRACTION`` (0.40) of the total positive contribution.

A previous implementation re-computed the total after every capping pass and
iterated up to five times "until convergence". That is mathematically
**non-convergent** whenever fewer than three comparable positive components
exist:

* 1 positive component  -> it is always 100 % of the running total.
* 2 equal positive components -> each is always 50 % of the running total.

In those cases the loop's ``changed`` flag never cleared, so it ran all five
passes and shrank each dominant component by ``0.40`` per pass
(``value * 0.40**5 ≈ 0.0102 * value``) instead of converging — silently
gutting the positive score of a high-conviction setup whose edge is
concentrated in one or two dimensions, with the outcome depending on the magic
iteration count ``5``.

The fix caps once against the *pre-cap* total, projecting every component onto
``min(raw, 0.40 * pre_cap_total)``. That bound is achievable, idempotent, and
independent of any iteration count.

`test_single_dominant_component_capped_once_not_crushed` pins that a lone
component is capped to ``raw * 0.40`` (not the old ``raw * 0.40**5`` crush).

`test_each_component_capped_to_fraction_of_precap_total` asserts the exact
single-pass projection over a seeded random sweep (repo convention: the
``*_invariants_property.py`` tests deliberately avoid a ``hypothesis``
dependency so the suite runs in every production workflow), catching both an
under-shoot (the old crush) and any component exceeding the cap.
"""

from __future__ import annotations

import random
import unittest.mock as _mock
from typing import Any

from open_prep import scorer as sc

# Feature inputs that feed the 15 positive-ish score components. Zeroing all of
# them (plus bias=0) makes every component vanish; we then re-inflate a chosen
# subset to control how concentrated the positive contribution is.
_ZEROABLE_FEATURE_KEYS = (
    "gap_pct_for_scoring",
    "sector_relative_gap",
    "rel_vol_capped",
    "momentum_z",
    "news_score",
    "ext_hours_score",
    "analyst_catalyst_score",
    "vwap_distance_pct",
    "freshness_decay",
    "institutional_quality",
    "estimate_revision_score",
    "ewma_score",
)

_POSITIVE_BREAKDOWN_KEYS = (
    "gap_component",
    "gap_sector_rel_component",
    "rvol_component",
    "macro_component",
    "momentum_component",
    "hvb_component",
    "earnings_bmo_component",
    "news_component",
    "ext_hours_component",
    "analyst_catalyst_component",
    "vwap_distance_component",
    "freshness_component",
    "institutional_component",
    "estimate_revision_component",
    "ewma_component",
)


def _base_quote(symbol: str = "TEST") -> dict[str, Any]:
    """Minimal quote that survives `filter_candidate` hard blocks."""
    return {
        "symbol": symbol,
        "price": 50.0,
        "gap_pct": 5.0,
        "gap_available": True,
        "volume": 1_000_000,
        "avgVolume": 800_000,
        "atr": 1.5,
        "momentum_z_score": 0.0,
        "volume_ratio": 1.5,
        "rsi": 55.0,
        "premarket_stale": False,
        "premarket_spread_bps": 50.0,
        "earnings_today": False,
        "earnings_risk_window": False,
        "split_today": False,
        "ipo_window": False,
        "previousClose": 47.5,
        "vwap": 49.0,
        "ext_hours_score": 0.5,
        "is_hvb": False,
        "premarket_change_pct": 5.0,
        "premarket_freshness_sec": 30.0,
    }


def _neutralized_fr() -> Any:
    """A passing FilterResult with every positive-component driver zeroed."""
    fr = sc.filter_candidate(_base_quote(), bias=0.0)
    f = fr.features
    for key in _ZEROABLE_FEATURE_KEYS:
        f[key] = 0.0
    f["is_hvb"] = False
    f["earnings_bmo"] = False
    return fr


def test_single_dominant_component_capped_once_not_crushed() -> None:
    """A lone positive component is capped once to 40% of the (pre-cap) total.

    Before the fix the component-cap loop re-computed the total after every
    pass and iterated five times, geometrically crushing a lone component to
    ``raw * 0.40**5`` (~1% of its value). The single-pass cap against the
    stable pre-cap total now bounds it to exactly ``raw * 0.40``.
    """
    fr = _neutralized_fr()
    # Only the gap component contributes; leave everything else at zero.
    fr.features["gap_pct_for_scoring"] = 8.0  # < GAP_CAP_ABS (10) => no clamp

    row = sc.score_candidate(fr, bias=0.0)
    breakdown = row["score_breakdown"]

    raw_gap = sc.DEFAULT_WEIGHTS["gap"] * max(
        min(8.0, sc.GAP_CAP_ABS), -sc.GAP_CAP_ABS
    )
    # Single-pass cap: lone component -> 40% of the pre-cap total (== raw_gap).
    expected = round(raw_gap * sc.SCORE_COMPONENT_CAP_FRACTION, 4)
    crushed = round(raw_gap * (sc.SCORE_COMPONENT_CAP_FRACTION**5), 4)

    positives = {
        k: breakdown[k] for k in _POSITIVE_BREAKDOWN_KEYS if breakdown[k] > 0.0
    }
    assert set(positives) == {"gap_component"}
    assert breakdown["gap_component"] == expected
    # Regression guard: must NOT be the old geometric-crush value.
    assert breakdown["gap_component"] != crushed
    assert breakdown["gap_component"] > crushed


def test_each_component_capped_to_fraction_of_precap_total() -> None:
    """Achievable invariant: each positive component == min(raw, 40% of the
    pre-cap total). Seeded sweep (repo convention: no hypothesis dependency).

    An *upper*-bound-only invariant would be trivially satisfied by the old
    geometric-crush bug (crushed values are smaller). This asserts the exact
    single-pass projection, so an under-shoot (crush) or a divergent loop is
    caught in both directions.
    """
    rng = random.Random(0x5C08E)
    # Pathological single-dominant case always first (formerly @example).
    cases = [(8.0, 0.0, 0.0)] + [
        (rng.uniform(0.0, 9.0), rng.uniform(0.0, 5.0), rng.uniform(0.0, 1.0))
        for _ in range(40)
    ]
    for gap, rvol, news in cases:
        def _make_fr(gap: float = gap, rvol: float = rvol, news: float = news) -> Any:
            fr = _neutralized_fr()
            fr.features["gap_pct_for_scoring"] = gap
            fr.features["rel_vol_capped"] = rvol
            fr.features["news_score"] = news
            return fr

        # Single uncapped run; derive precap_total from it.
        with _mock.patch.object(sc, "SCORE_COMPONENT_CAP_FRACTION", 1.0):
            raw_breakdown = sc.score_candidate(_make_fr(), bias=0.0)["score_breakdown"]
        precap_total = sum(
            raw_breakdown[k] for k in _POSITIVE_BREAKDOWN_KEYS if raw_breakdown[k] > 0.0
        )
        if precap_total <= 0.0:
            continue
        cap = sc.SCORE_COMPONENT_CAP_FRACTION * precap_total

        capped_breakdown = sc.score_candidate(_make_fr(), bias=0.0)["score_breakdown"]

        eps = 1e-3  # tolerate 4-decimal rounding in score_breakdown
        for key in _POSITIVE_BREAKDOWN_KEYS:
            raw_v = raw_breakdown[key]
            if raw_v <= 0.0:
                continue
            expected = min(raw_v, cap)
            assert abs(capped_breakdown[key] - expected) <= eps, (
                f"gap={gap} rvol={rvol} news={news} {key}: "
                f"got {capped_breakdown[key]}, expected {expected}"
            )
        positives = [
            capped_breakdown[k] for k in _POSITIVE_BREAKDOWN_KEYS if capped_breakdown[k] > 0.0
        ]
        assert max(positives) <= cap + eps

