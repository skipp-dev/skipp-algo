"""EV-05 — per-family walk-forward / embargo config tests."""
from __future__ import annotations

from typing import get_args

import pytest

from governance.family_walkforward import (
    FAMILY_WALKFORWARD,
    family_outcome_horizon,
    get_family_config,
    validate_family_coverage,
)
from governance.types import EventFamily
from smc_core.label_horizons import LABEL_HORIZON_BARS

_FAMILIES = sorted(get_args(EventFamily))


def test_every_family_has_a_config() -> None:
    validate_family_coverage()
    assert sorted(FAMILY_WALKFORWARD) == _FAMILIES


@pytest.mark.parametrize("family", _FAMILIES)
def test_embargo_is_twice_the_label_window(family: str) -> None:
    cfg = get_family_config(family)
    # López de Prado leakage guard: embargo_bars = 2 * LABEL-resolution window
    # (audit 2026-07-13). It is keyed to the label window, NOT the trade-exit
    # hold ``family_outcome_horizon`` — those are distinct concepts.
    assert cfg.embargo_bars == 2 * LABEL_HORIZON_BARS[family]
    assert cfg.embargo_bars >= LABEL_HORIZON_BARS[family]
    assert cfg.embargo_bars >= 1


@pytest.mark.parametrize("family", _FAMILIES)
def test_config_is_well_formed(family: str) -> None:
    cfg = get_family_config(family)
    assert cfg.scheme in ("rolling", "anchored", "expanding")
    assert cfg.n_folds >= 1


def test_unknown_family_raises() -> None:
    with pytest.raises(KeyError):
        get_family_config("NOPE")
    with pytest.raises(KeyError):
        family_outcome_horizon("NOPE")
