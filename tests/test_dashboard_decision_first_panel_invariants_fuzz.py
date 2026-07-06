"""Property-based invariants for dashboard.decision_first_panel helpers.

Focuses on silent crashes, NaN propagation in sparklines, and robust handling
of malformed decision/blocker payloads.
"""

from __future__ import annotations

from typing import Any

import hypothesis.strategies as st
from hypothesis import given, settings

from dashboard import decision_first_panel as dfp

# ---------------------------------------------------------------------------
# sparkline invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    values=st.lists(
        st.floats(
            allow_nan=False,
            allow_infinity=False,
            min_value=-1e9,
            max_value=1e9,
        ),
        min_size=0,
        max_size=100,
    )
)
def test_sparkline_bounded_finite_values_never_crashes(values: list[float]) -> None:
    dfp.sparkline(values)


@settings(max_examples=500)
@given(
    values=st.lists(
        st.floats(
            allow_nan=False,
            allow_infinity=False,
            min_value=-1e9,
            max_value=1e9,
        ),
        min_size=1,
        max_size=100,
    )
)
def test_sparkline_bounded_finite_length_matches_input(values: list[float]) -> None:
    result = dfp.sparkline(values)
    assert len(result) == len(values)


def test_sparkline_nan_does_not_crash() -> None:
    dfp.sparkline([1.0, float("nan"), 3.0])


def test_sparkline_extreme_values_does_not_crash() -> None:
    dfp.sparkline([1.7976931348623157e308, -9.9792015476736e291])


def test_sparkline_constant_input_is_mid_char() -> None:
    # _SPARK_CHARS has 8 chars; index 4 is the middle char '▅'.
    assert dfp.sparkline([5.0, 5.0, 5.0]) == "▅" * 3


def test_sparkline_empty_is_empty() -> None:
    assert dfp.sparkline([]) == ""


# ---------------------------------------------------------------------------
# _metrics_summary invariants
# ---------------------------------------------------------------------------


@settings(max_examples=500)
@given(metrics=st.dictionaries(st.text(), st.one_of(st.floats(), st.integers())))
def test_metrics_summary_numbers_never_crashes(metrics: dict[str, Any]) -> None:
    dfp._metrics_summary(metrics)


def test_metrics_summary_empty_string_value_does_not_crash() -> None:
    dfp._metrics_summary({"sharpe": ""})


def test_metrics_summary_empty_returns_placeholder() -> None:
    assert dfp._metrics_summary({}) == "(no metrics)"


# ---------------------------------------------------------------------------
# _top_blocker invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    blockers=st.lists(
        st.fixed_dictionaries(
            {
                "severity": st.text(),
                "check": st.text(),
                "message": st.text(),
            }
        ),
        min_size=0,
        max_size=20,
    )
)
def test_top_blocker_complete_dict_list_never_crashes(blockers: list[dict[str, str]]) -> None:
    dfp._top_blocker(blockers)


def test_top_blocker_missing_keys_does_not_crash() -> None:
    """BUG REPRO: missing 'check' or 'message' keys must not crash."""
    result = dfp._top_blocker([{"severity": "critical"}])
    assert isinstance(result, str)


def test_top_blocker_empty_returns_empty() -> None:
    assert dfp._top_blocker([]) == ""


def test_top_blocker_well_formed_returns_formatted_string() -> None:
    result = dfp._top_blocker([{"severity": "critical", "check": "drawdown", "message": "too deep"}])
    assert result == "critical/drawdown: too deep"


# ---------------------------------------------------------------------------
# build_card / render_panel invariants
# ---------------------------------------------------------------------------


@settings(max_examples=500)
@given(
    decision=st.fixed_dictionaries(
        {"family": st.text()},
        optional={
            "posture": st.text(),
            "promoted": st.booleans(),
            "blockers": st.lists(
                st.fixed_dictionaries(
                    {
                        "severity": st.text(),
                        "check": st.text(),
                        "message": st.text(),
                    }
                ),
                min_size=0,
                max_size=5,
            ),
            "metrics": st.dictionaries(st.text(), st.one_of(st.floats(), st.integers())),
        },
    ),
    history=st.one_of(
        st.none(),
        st.lists(
            st.floats(allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9),
            min_size=0,
            max_size=50,
        ),
    ),
)
def test_build_card_never_crashes_on_well_typed_decisions(decision: dict[str, Any], history) -> None:
    dfp.build_card(decision, walkforward_history=history or [])


def test_render_panel_string_metrics_does_not_crash() -> None:
    dfp.render_panel([{"family": "x", "metrics": "0"}])


@settings(max_examples=500)
@given(
    decisions=st.lists(
        st.fixed_dictionaries(
            {"family": st.text()},
            optional={
                "posture": st.text(),
                "promoted": st.booleans(),
                "blockers": st.lists(
                    st.fixed_dictionaries(
                        {
                            "severity": st.text(),
                            "check": st.text(),
                            "message": st.text(),
                        }
                    ),
                    min_size=0,
                    max_size=5,
                ),
                "metrics": st.dictionaries(st.text(), st.one_of(st.floats(), st.integers())),
            },
        ),
        min_size=0,
        max_size=20,
    )
)
def test_render_panel_never_crashes_on_well_typed_decisions(decisions: list[dict[str, Any]]) -> None:
    dfp.render_panel(decisions)
