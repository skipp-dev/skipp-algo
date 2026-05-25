"""Property tests for ``smc_core.serialization`` pure helpers.

Pins the contract of the snapshot serialiser shared by every artifact
writer (``ensemble_quality``, ``scoring``, ``smc_*``, dashboard exports):

  * :func:`smc_core.serialization._drop_nones`
  * :func:`smc_core.serialization.snapshot_to_dict`

Continues the PQ Re-Audit Tier-1 spillover series
(PRs #2350, #2363, #2366, #2370, #2371, #2372, #2373, #2374, #2375,
#2376, #2377). Pure stdlib; ≤ 1s.
"""

from __future__ import annotations

import copy
import math

import pytest

from smc_core.serialization import _drop_nones, snapshot_to_dict
from smc_core.types import (
    SmcLayered,
    SmcMeta,
    SmcSnapshot,
    SmcStructure,
    TimedVolumeInfo,
    VolumeInfo,
)


# ---------------------------------------------------------------------------
# _drop_nones — scalar pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    (0, 0.0, -1, 1, 3.14, "", "x", True, False, b"bytes", (1, 2), {1, 2}),
)
def test_drop_nones_scalar_pass_through(value: object) -> None:
    """Non-dict / non-list scalars (including falsy ones) are returned as-is."""
    assert _drop_nones(value) is value


def test_drop_nones_top_level_none_is_returned_unchanged() -> None:
    """`None` at top level is not stripped — only `None`-valued **dict entries** are."""
    assert _drop_nones(None) is None


def test_drop_nones_nan_pass_through() -> None:
    """NaN is a finite Python float and must pass through (not be confused with None)."""
    out = _drop_nones(float("nan"))
    assert isinstance(out, float)
    assert math.isnan(out)


# ---------------------------------------------------------------------------
# _drop_nones — dict
# ---------------------------------------------------------------------------


def test_drop_nones_dict_removes_none_values() -> None:
    assert _drop_nones({"a": 1, "b": None, "c": "x"}) == {"a": 1, "c": "x"}


def test_drop_nones_dict_keeps_falsy_non_none_values() -> None:
    """Falsy values other than `None` (0, '', False, [], {}) are kept."""
    out = _drop_nones({"zero": 0, "empty_str": "", "false": False, "empty_list": [], "empty_dict": {}, "none": None})
    assert out == {"zero": 0, "empty_str": "", "false": False, "empty_list": [], "empty_dict": {}}


def test_drop_nones_dict_recurses_into_nested_dict() -> None:
    assert _drop_nones({"a": {"b": None, "c": 1, "d": {"e": None, "f": 2}}}) == {"a": {"c": 1, "d": {"f": 2}}}


def test_drop_nones_dict_preserves_insertion_order() -> None:
    src = {"z": 1, "a": None, "m": 2, "b": 3}
    assert list(_drop_nones(src).keys()) == ["z", "m", "b"]


def test_drop_nones_dict_empty_returns_empty_dict() -> None:
    assert _drop_nones({}) == {}


def test_drop_nones_dict_does_not_mutate_input() -> None:
    src = {"a": 1, "b": None, "c": {"d": None, "e": 2}}
    snapshot = copy.deepcopy(src)
    _drop_nones(src)
    assert src == snapshot


# ---------------------------------------------------------------------------
# _drop_nones — list
# ---------------------------------------------------------------------------


def test_drop_nones_list_keeps_none_elements() -> None:
    """Only `None`-valued **dict entries** are stripped — `None` elements in lists are kept."""
    assert _drop_nones([1, None, 2]) == [1, None, 2]


def test_drop_nones_list_recurses_into_nested_dicts() -> None:
    assert _drop_nones([{"a": None, "b": 1}, {"c": 2, "d": None}]) == [{"b": 1}, {"c": 2}]


def test_drop_nones_list_recurses_into_nested_lists() -> None:
    assert _drop_nones([[{"a": None, "b": 1}], [{"c": 2}]]) == [[{"b": 1}], [{"c": 2}]]


def test_drop_nones_list_empty_returns_empty_list() -> None:
    assert _drop_nones([]) == []


# ---------------------------------------------------------------------------
# _drop_nones — deeply nested + idempotency
# ---------------------------------------------------------------------------


def test_drop_nones_deeply_nested_structure() -> None:
    src = {
        "a": [
            {"x": None, "y": 1, "z": {"p": None, "q": [None, {"r": None, "s": 2}]}},
            None,  # list element None — kept
        ],
        "b": None,
        "c": [],
    }
    expected = {
        "a": [
            {"y": 1, "z": {"q": [None, {"s": 2}]}},
            None,
        ],
        "c": [],
    }
    assert _drop_nones(src) == expected


def test_drop_nones_idempotent() -> None:
    """Running `_drop_nones` twice yields the same result as running it once."""
    src = {"a": 1, "b": None, "c": [{"d": None, "e": 2}], "f": {"g": None}}
    once = _drop_nones(src)
    twice = _drop_nones(once)
    assert once == twice


# ---------------------------------------------------------------------------
# snapshot_to_dict
# ---------------------------------------------------------------------------


def _minimal_snapshot() -> SmcSnapshot:
    return SmcSnapshot(
        symbol="AAPL",
        timeframe="1H",
        generated_at=1234567.0,
        schema_version="v1",
        structure=SmcStructure(),
        meta=SmcMeta(
            symbol="AAPL",
            timeframe="1H",
            asof_ts=1234567.0,
            volume=TimedVolumeInfo(
                value=VolumeInfo(regime="NORMAL", thin_fraction=0.0),
                asof_ts=1234567.0,
                stale=False,
            ),
        ),
        layered=SmcLayered(),
    )


def test_snapshot_to_dict_returns_dict_with_top_level_fields() -> None:
    out = snapshot_to_dict(_minimal_snapshot())
    assert isinstance(out, dict)
    assert out["symbol"] == "AAPL"
    assert out["timeframe"] == "1H"
    assert out["generated_at"] == 1234567.0
    assert out["schema_version"] == "v1"


def test_snapshot_to_dict_drops_none_meta_fields() -> None:
    """Optional `meta` fields default to `None` and must be stripped from output."""
    out = snapshot_to_dict(_minimal_snapshot())
    meta = out["meta"]
    # None-defaulted optional fields are stripped:
    for stripped in ("technical", "news", "event_risk", "market_regime"):
        assert stripped not in meta, f"{stripped!r} should be stripped from meta"
    # Required + non-None fields survive:
    assert meta["symbol"] == "AAPL"
    assert meta["asof_ts"] == 1234567.0
    assert meta["volume"]["value"]["regime"] == "NORMAL"


def test_snapshot_to_dict_includes_default_factory_lists() -> None:
    out = snapshot_to_dict(_minimal_snapshot())
    # Empty default-factory lists/dicts are NOT None → kept.
    assert out["meta"]["enriched_news"] == []
    assert out["meta"]["provenance"] == []
    assert out["structure"]["bos"] == []
    assert out["structure"]["orderblocks"] == []
    assert out["structure"]["fvg"] == []
    assert out["structure"]["liquidity_sweeps"] == []
    assert out["layered"]["zone_styles"] == {}


def test_snapshot_to_dict_without_product_cut_omits_key() -> None:
    out = snapshot_to_dict(_minimal_snapshot())
    assert "product_cut" not in out


def test_snapshot_to_dict_with_product_cut_attaches_cleaned_copy() -> None:
    cut = {"keep": 1, "drop": None, "nested": {"k": 1, "n": None}}
    out = snapshot_to_dict(_minimal_snapshot(), product_cut=cut)
    assert out["product_cut"] == {"keep": 1, "nested": {"k": 1}}


def test_snapshot_to_dict_product_cut_input_not_mutated() -> None:
    cut = {"keep": 1, "drop": None, "nested": {"k": 1, "n": None}}
    snapshot = copy.deepcopy(cut)
    snapshot_to_dict(_minimal_snapshot(), product_cut=cut)
    assert cut == snapshot


def test_snapshot_to_dict_product_cut_empty_dict_kept() -> None:
    """`product_cut={}` is *not* None → key is present with empty dict."""
    out = snapshot_to_dict(_minimal_snapshot(), product_cut={})
    assert out["product_cut"] == {}
