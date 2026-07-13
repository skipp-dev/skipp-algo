"""Horizon SSOT pin (audit 2026-07-13, finding #4).

The governance walk-forward purge/embargo MUST use the same per-family
label-resolution horizon as the measurement-evidence outcome labels, otherwise
the embargo (``2 * horizon``) can be shorter than the label window it is meant
to purge and future labels leak into training folds. This test pins the three
layers together so they cannot drift apart again.
"""
from __future__ import annotations

import pytest

from governance.family_event_adapter import (
    _BOS_LOOKAHEAD_BARS as _ADAPTER_BOS,
)
from governance.family_event_adapter import (
    _FVG_LOOKAHEAD_BARS as _ADAPTER_FVG,
)
from governance.family_event_adapter import (
    _SWEEP_LOOKAHEAD_BARS as _ADAPTER_SWEEP,
)
from governance.family_event_adapter import (
    _ZONE_LOOKAHEAD_BARS as _ADAPTER_ZONE,
)
from governance.family_walkforward import family_outcome_horizon, get_family_config
from smc_core.label_horizons import LABEL_HORIZON_BARS, label_horizon_bars
from smc_integration.measurement_evidence import (
    _BOS_LOOKAHEAD_BARS,
    _FVG_LOOKAHEAD_BARS,
    _SWEEP_LOOKAHEAD_BARS,
    _ZONE_LOOKAHEAD_BARS,
)

# The corrected, pinned windows. OB/FVG/SWEEP were 6/4/3 before the fix.
_EXPECTED = {"BOS": 8, "OB": 12, "FVG": 20, "SWEEP": 8}
_MEASUREMENT_LABEL_WINDOW = {
    "BOS": _BOS_LOOKAHEAD_BARS,
    "OB": _ZONE_LOOKAHEAD_BARS,
    "FVG": _FVG_LOOKAHEAD_BARS,
    "SWEEP": _SWEEP_LOOKAHEAD_BARS,
}
_ADAPTER_FORWARD_WINDOW = {
    "BOS": _ADAPTER_BOS,
    "OB": _ADAPTER_ZONE,
    "FVG": _ADAPTER_FVG,
    "SWEEP": _ADAPTER_SWEEP,
}


def test_ssot_values_are_the_pinned_windows() -> None:
    assert LABEL_HORIZON_BARS == _EXPECTED


@pytest.mark.parametrize("family", sorted(_EXPECTED))
def test_measurement_labels_match_ssot(family: str) -> None:
    assert _MEASUREMENT_LABEL_WINDOW[family] == LABEL_HORIZON_BARS[family]


@pytest.mark.parametrize("family", sorted(_EXPECTED))
def test_adapter_forward_window_matches_ssot(family: str) -> None:
    # The third copy: family_event_adapter's forward window must equal the SSOT
    # so realized_return sees the same window the measurement labels resolve over.
    assert _ADAPTER_FORWARD_WINDOW[family] == LABEL_HORIZON_BARS[family]


@pytest.mark.parametrize("family", sorted(_EXPECTED))
def test_label_horizon_bars_accessor_matches_ssot(family: str) -> None:
    assert label_horizon_bars(family) == LABEL_HORIZON_BARS[family]


@pytest.mark.parametrize("family", sorted(_EXPECTED))
def test_embargo_is_keyed_to_label_window_not_trade_hold(family: str) -> None:
    # The fix: embargo is 2 * LABEL window, decoupled from the (separate) trade
    # hold. It must fully cover the label-resolution window it is meant to purge.
    embargo = get_family_config(family).embargo_bars
    assert embargo == 2 * LABEL_HORIZON_BARS[family]
    assert embargo >= _MEASUREMENT_LABEL_WINDOW[family]


def test_embargo_no_longer_under_purges_ob_fvg_sweep() -> None:
    # Regression guard: pre-fix embargo was 2*hold = 12/8/6 for OB/FVG/SWEEP,
    # shorter than the 12/20/8 label windows. Now 2*label = 24/40/16.
    assert get_family_config("OB").embargo_bars == 24
    assert get_family_config("FVG").embargo_bars == 40
    assert get_family_config("SWEEP").embargo_bars == 16
    for family in ("OB", "FVG", "SWEEP"):
        assert get_family_config(family).embargo_bars >= _MEASUREMENT_LABEL_WINDOW[family]


def test_trade_hold_is_distinct_from_label_window() -> None:
    # The trade-exit hold (realized_return) is intentionally NOT the label window;
    # this pins the two concepts apart so they are not re-merged by mistake.
    assert family_outcome_horizon("OB") == 6
    assert family_outcome_horizon("FVG") == 4
    assert family_outcome_horizon("SWEEP") == 3
    assert family_outcome_horizon("BOS") == 8


def test_label_horizon_bars_unknown_family_raises() -> None:
    with pytest.raises(KeyError):
        label_horizon_bars("NOT_A_FAMILY")
