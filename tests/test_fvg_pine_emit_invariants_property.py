"""Property tests for ``smc_core.fvg_pine_emit`` (Amendment A1.C).

Pins the determinism + threshold contract of the tri-axis FVG health
Pine codegen used by the ``SMC_Core_Engine.pine`` dashboard:

  * :func:`smc_core.fvg_pine_emit._safe_token`
  * :func:`smc_core.fvg_pine_emit._status_for`
  * :func:`smc_core.fvg_pine_emit._aggregate_session_vol`
  * :func:`smc_core.fvg_pine_emit.emit_fvg_pine_constants`
  * :func:`smc_core.fvg_pine_emit.emit_fvg_pine_block`

Existing unit tests cover the smoke path against a fixed corpus. This
file pins the harder invariants — boundary thresholds (0.70 / 0.55 /
< 0.55), `htf_bias` collapse, `min_events` override, deterministic
lexicographic sort, percent-rounding rule, and `_safe_token` edge
cases (special-only → "UNKNOWN", underscore preservation, numeric).

Continues the PQ Re-Audit Tier-1 spillover series (#2350, #2363, #2366,
#2370, #2371, #2372, #2373, #2374, #2375, #2376, #2377, #2378, #2379).
"""

from __future__ import annotations

from typing import Any

import pytest

from smc_core.fvg_pine_emit import (
    PINE_PREFIX,
    _aggregate_session_vol,
    _safe_token,
    _status_for,
    emit_fvg_pine_block,
    emit_fvg_pine_constants,
)


# ---------------------------------------------------------------------------
# PINE_PREFIX
# ---------------------------------------------------------------------------


def test_pine_prefix_value() -> None:
    """The dashboard contract pins the constant prefix."""
    assert PINE_PREFIX == "FVG_HEALTH"


# ---------------------------------------------------------------------------
# _safe_token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ny_am", "NY_AM"),         # lower → upper
        ("NY_AM", "NY_AM"),          # already canonical
        ("NY-AM!", "NYAM"),          # punctuation stripped
        ("NY AM", "NYAM"),           # spaces stripped (space is not alnum)
        ("HIGH_VOL", "HIGH_VOL"),    # underscore preserved
        ("HIGH VOL", "HIGHVOL"),
        ("vol2", "VOL2"),            # digits preserved
        ("123", "123"),              # all-digit allowed
        ("a_b_c", "A_B_C"),
        ("", "UNKNOWN"),             # empty → UNKNOWN
        ("---", "UNKNOWN"),          # all-special → UNKNOWN
        ("!@#$%", "UNKNOWN"),
        ("   ", "UNKNOWN"),
    ],
)
def test_safe_token_normalisation(raw: str, expected: str) -> None:
    assert _safe_token(raw) == expected


def test_safe_token_coerces_non_string_input() -> None:
    """Non-string inputs are stringified before normalisation."""
    assert _safe_token(123) == "123"
    assert _safe_token(None) == "NONE"
    assert _safe_token(True) == "TRUE"


# ---------------------------------------------------------------------------
# _status_for — threshold table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hit_rate", "n_events", "min_events", "expected"),
    [
        # OK band (≥ 0.70):
        (0.70, 12, 12, "OK"),       # boundary inclusive
        (0.85, 100, 12, "OK"),
        (1.00, 12, 12, "OK"),
        # WARN band (≥ 0.55, < 0.70):
        (0.55, 12, 12, "WARN"),     # boundary inclusive
        (0.60, 12, 12, "WARN"),
        (0.699999, 12, 12, "WARN"),
        # WEAK band (< 0.55, n ≥ min):
        (0.5499, 12, 12, "WEAK"),
        (0.00, 12, 12, "WEAK"),
        (0.30, 100, 12, "WEAK"),
        # INSUF (n < min_events) — takes precedence over hit rate:
        (1.00, 11, 12, "INSUF"),
        (0.00, 0, 12, "INSUF"),
        (0.85, 5, 12, "INSUF"),
        # INSUF on missing hit rate (n_events == 0 → hit_rate None upstream):
        (None, 12, 12, "INSUF"),
        (None, 0, 12, "INSUF"),
        # min_events override:
        (0.70, 5, 5, "OK"),
        (0.55, 1, 1, "WARN"),
    ],
)
def test_status_for_threshold_table(
    hit_rate: float | None, n_events: int, min_events: int, expected: str
) -> None:
    assert _status_for(hit_rate, n_events, min_events=min_events) == expected


def test_status_for_insuf_precedence_over_hit_rate() -> None:
    """Even a 100% hit rate is INSUF when n_events < min_events."""
    assert _status_for(1.0, 0, min_events=12) == "INSUF"
    assert _status_for(1.0, 11, min_events=12) == "INSUF"
    assert _status_for(1.0, 12, min_events=12) == "OK"  # boundary


# ---------------------------------------------------------------------------
# _aggregate_session_vol
# ---------------------------------------------------------------------------


def test_aggregate_session_vol_sums_repeated_cells() -> None:
    """Multiple buckets on the same (session, vol) sum n_events and hits."""
    report: dict[str, Any] = {
        "buckets": [
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 10, "hits": 7},
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 6, "hits": 5},
            {"session": "ASIA", "vol_regime": "LOW", "n_events": 4, "hits": 1},
        ],
    }
    cells = _aggregate_session_vol(report)
    assert cells[("NY_AM", "NORMAL")] == {"n_events": 16, "hits": 12, "buckets": 2}
    assert cells[("ASIA", "LOW")] == {"n_events": 4, "hits": 1, "buckets": 1}


def test_aggregate_session_vol_ignores_htf_bias() -> None:
    """htf_bias is intentionally collapsed away — same (session, vol) buckets fold."""
    report: dict[str, Any] = {
        "buckets": [
            {"session": "NY_AM", "vol_regime": "NORMAL", "htf_bias": "BULL", "n_events": 5, "hits": 4},
            {"session": "NY_AM", "vol_regime": "NORMAL", "htf_bias": "BEAR", "n_events": 5, "hits": 1},
        ],
    }
    cells = _aggregate_session_vol(report)
    assert list(cells.keys()) == [("NY_AM", "NORMAL")]
    assert cells[("NY_AM", "NORMAL")] == {"n_events": 10, "hits": 5, "buckets": 2}


def test_aggregate_session_vol_missing_fields_use_unknown_and_zero() -> None:
    """Missing session/vol → "UNKNOWN"; missing n_events/hits → 0."""
    report: dict[str, Any] = {"buckets": [{}]}
    cells = _aggregate_session_vol(report)
    assert cells == {("UNKNOWN", "UNKNOWN"): {"n_events": 0, "hits": 0, "buckets": 1}}


def test_aggregate_session_vol_none_buckets_returns_empty() -> None:
    assert _aggregate_session_vol({}) == {}
    assert _aggregate_session_vol({"buckets": None}) == {}
    assert _aggregate_session_vol({"buckets": []}) == {}


def test_aggregate_session_vol_coerces_none_counts_to_zero() -> None:
    """`int(None or 0)` keeps the function robust against partial inputs."""
    report: dict[str, Any] = {
        "buckets": [{"session": "X", "vol_regime": "Y", "n_events": None, "hits": None}],
    }
    cells = _aggregate_session_vol(report)
    assert cells[("X", "Y")] == {"n_events": 0, "hits": 0, "buckets": 1}


# ---------------------------------------------------------------------------
# emit_fvg_pine_constants — header & line shape
# ---------------------------------------------------------------------------


def _report(buckets: list[dict[str, Any]], *, min_events: int = 12) -> dict[str, Any]:
    return {"buckets": buckets, "min_events": min_events}


def test_emit_empty_report_returns_only_header() -> None:
    out = emit_fvg_pine_constants(_report([]))
    assert len(out) == 1
    assert out[0].startswith("// ── FVG Tri-Axis Health")


def test_emit_two_lines_per_cell() -> None:
    report = _report(
        [
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 20, "hits": 18},
            {"session": "ASIA", "vol_regime": "LOW", "n_events": 4, "hits": 1},
        ]
    )
    out = emit_fvg_pine_constants(report)
    decls = [ln for ln in out if ln.startswith("export const")]
    # 2 cells × (value + status) = 4
    assert len(decls) == 4


def test_emit_cells_sorted_lexicographically() -> None:
    """Output order is deterministic: sorted by (session, vol_regime)."""
    report = _report(
        [
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 20, "hits": 18},
            {"session": "ASIA", "vol_regime": "HIGH", "n_events": 20, "hits": 18},
            {"session": "ASIA", "vol_regime": "LOW", "n_events": 20, "hits": 18},
            {"session": "LONDON", "vol_regime": "NORMAL", "n_events": 20, "hits": 18},
        ]
    )
    out = emit_fvg_pine_constants(report)
    idents = [ln.split("=")[0].strip() for ln in out if ln.startswith("export const")]
    # Two lines per cell (value + status) — value comes first per cell.
    value_idents = [s for s in idents if not s.endswith("_STATUS")]
    # Strip "export const string " prefix
    names = [s.removeprefix("export const string ").strip() for s in value_idents]
    assert names == [
        f"{PINE_PREFIX}_ASIA_HIGH",
        f"{PINE_PREFIX}_ASIA_LOW",
        f"{PINE_PREFIX}_LONDON_NORMAL",
        f"{PINE_PREFIX}_NY_AM_NORMAL",
    ]


def test_emit_value_status_pair_interleaved_per_cell() -> None:
    """For every cell, the VALUE line immediately precedes the STATUS line."""
    report = _report(
        [
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 20, "hits": 18},
            {"session": "ASIA", "vol_regime": "LOW", "n_events": 4, "hits": 1},
        ]
    )
    out = emit_fvg_pine_constants(report)
    decls = [ln for ln in out if ln.startswith("export const")]
    # Pairs must be (value, status):
    for i in range(0, len(decls), 2):
        value_line = decls[i]
        status_line = decls[i + 1]
        # status ident == value ident + "_STATUS"
        value_ident = value_line.split("=", 1)[0].strip().split()[-1]
        status_ident = status_line.split("=", 1)[0].strip().split()[-1]
        assert status_ident == f"{value_ident}_STATUS"


# ---------------------------------------------------------------------------
# emit_fvg_pine_constants — content
# ---------------------------------------------------------------------------


def test_emit_renders_percent_with_round_half_to_even() -> None:
    """Hit-rate percent uses Python's banker's rounding (``round``).

    5/40 = 0.125 → 12.5%. Banker's rounding rounds 12.5 to the nearest
    even integer = 12 (a non-banker round-half-up would yield 13).
    """
    report = _report([{"session": "X", "vol_regime": "Y", "n_events": 40, "hits": 5}])
    block = emit_fvg_pine_block(report)
    assert f'{PINE_PREFIX}_X_Y = "12% (n=40)"' in block


def test_emit_insufficient_uses_dedicated_string() -> None:
    report = _report([{"session": "X", "vol_regime": "Y", "n_events": 4, "hits": 3}])
    block = emit_fvg_pine_block(report)
    assert f'{PINE_PREFIX}_X_Y = "insufficient (n=4)"' in block
    assert f'{PINE_PREFIX}_X_Y_STATUS = "INSUF"' in block


def test_emit_zero_events_cell_renders_insufficient_n0() -> None:
    report = _report([{"session": "X", "vol_regime": "Y", "n_events": 0, "hits": 0}])
    block = emit_fvg_pine_block(report)
    assert f'{PINE_PREFIX}_X_Y = "insufficient (n=0)"' in block
    assert f'{PINE_PREFIX}_X_Y_STATUS = "INSUF"' in block


def test_emit_status_thresholds_end_to_end() -> None:
    report = _report(
        [
            # 14/20 = 0.70 → OK (boundary)
            {"session": "A", "vol_regime": "OK", "n_events": 20, "hits": 14},
            # 11/20 = 0.55 → WARN (boundary)
            {"session": "B", "vol_regime": "WARN", "n_events": 20, "hits": 11},
            # 10/20 = 0.50 → WEAK
            {"session": "C", "vol_regime": "WEAK", "n_events": 20, "hits": 10},
            # n=5 < min_events=12 → INSUF
            {"session": "D", "vol_regime": "INSUF", "n_events": 5, "hits": 5},
        ]
    )
    block = emit_fvg_pine_block(report)
    assert f'{PINE_PREFIX}_A_OK_STATUS = "OK"' in block
    assert f'{PINE_PREFIX}_B_WARN_STATUS = "WARN"' in block
    assert f'{PINE_PREFIX}_C_WEAK_STATUS = "WEAK"' in block
    assert f'{PINE_PREFIX}_D_INSUF_STATUS = "INSUF"' in block


def test_emit_min_events_default_is_twelve() -> None:
    """Missing `min_events` defaults to 12."""
    # n=11 with no min_events key → INSUF (default 12)
    report: dict[str, Any] = {
        "buckets": [{"session": "X", "vol_regime": "Y", "n_events": 11, "hits": 11}],
    }
    block = emit_fvg_pine_block(report)
    assert f'{PINE_PREFIX}_X_Y = "insufficient (n=11)"' in block


def test_emit_min_events_override_respected() -> None:
    report = _report(
        [{"session": "X", "vol_regime": "Y", "n_events": 8, "hits": 8}],
        min_events=8,
    )
    block = emit_fvg_pine_block(report)
    assert f'{PINE_PREFIX}_X_Y = "100% (n=8)"' in block
    assert f'{PINE_PREFIX}_X_Y_STATUS = "OK"' in block


def test_emit_safe_token_strips_specials_in_idents() -> None:
    """`session=NY-AM!` and `vol_regime=HIGH VOL` collapse to `NYAM_HIGHVOL`."""
    report = _report(
        [{"session": "NY-AM!", "vol_regime": "HIGH VOL", "n_events": 20, "hits": 18}],
    )
    block = emit_fvg_pine_block(report)
    assert f"{PINE_PREFIX}_NYAM_HIGHVOL =" in block
    assert f"{PINE_PREFIX}_NYAM_HIGHVOL_STATUS =" in block


def test_emit_unknown_cell_when_session_or_vol_missing() -> None:
    report = _report([{"n_events": 20, "hits": 18}])
    block = emit_fvg_pine_block(report)
    assert f"{PINE_PREFIX}_UNKNOWN_UNKNOWN =" in block


# ---------------------------------------------------------------------------
# Determinism & emit_fvg_pine_block
# ---------------------------------------------------------------------------


def test_emit_block_equals_constants_joined_with_newline() -> None:
    report = _report(
        [
            {"session": "B", "vol_regime": "Y", "n_events": 20, "hits": 18},
            {"session": "A", "vol_regime": "X", "n_events": 4, "hits": 1},
        ]
    )
    assert emit_fvg_pine_block(report) == "\n".join(emit_fvg_pine_constants(report))


def test_emit_deterministic_under_input_reordering() -> None:
    """Reordering input buckets must NOT change output (sort key is deterministic)."""
    buckets = [
        {"session": "B", "vol_regime": "Y", "n_events": 20, "hits": 18},
        {"session": "A", "vol_regime": "X", "n_events": 14, "hits": 9},
        {"session": "A", "vol_regime": "Z", "n_events": 4, "hits": 1},
    ]
    out_a = emit_fvg_pine_block(_report(buckets))
    out_b = emit_fvg_pine_block(_report(list(reversed(buckets))))
    assert out_a == out_b


def test_emit_deterministic_repeated_calls() -> None:
    report = _report(
        [
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 20, "hits": 18},
            {"session": "ASIA", "vol_regime": "LOW", "n_events": 4, "hits": 1},
        ]
    )
    assert emit_fvg_pine_block(report) == emit_fvg_pine_block(report)


def test_emit_does_not_mutate_input_report() -> None:
    import copy

    report = _report(
        [
            {"session": "NY_AM", "vol_regime": "NORMAL", "n_events": 20, "hits": 18},
            {"session": "ASIA", "vol_regime": "LOW", "n_events": 4, "hits": 1},
        ]
    )
    snapshot = copy.deepcopy(report)
    emit_fvg_pine_constants(report)
    assert report == snapshot
