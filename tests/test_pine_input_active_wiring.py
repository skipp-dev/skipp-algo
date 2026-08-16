"""SMC_Long_Dip_Suite.pine — the `active =` master→dependent wiring (2026-08-16).

Pine's July-2025 ``active`` input parameter greys dependent inputs while
their master toggle is off. This ledger freezes WHICH inputs hang on WHICH
master, deliberately conservative: engine parameters that act regardless of
a display toggle (swing_length, EMA lengths, score weights) and multi-master
cases (vwap_session, market EMA lengths) are NOT wired, and masters are
never greyed by anything. A new wired input extends _WIRING in the same
commit — the completeness test measures the WHOLE file, not a sample.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SUITE = Path(__file__).resolve().parents[1] / "SMC_Long_Dip_Suite.pine"

_WIRING: dict[str, tuple[str, ...]] = {
    "enable_ltf_sampling": (
        "use_ltf_for_strict_entry", "allow_strict_entry_without_ltf",
        "ltf_auto_select", "ltf_timeframe", "ltf_bias_hint",
        "show_dashboard_ltf", "max_ltf_ratio", "max_ltf_samples_per_bar",
    ),
    "use_trade_session_gate": ("trade_entry_session", "block_entries_outside_session"),
    "use_opening_range_gate": ("opening_range_minutes", "opening_range_bias_mode"),
    "use_index_gate": ("index_gate_symbol",),
    "use_sector_gate": ("sector_gate_symbol",),
    "use_breadth_symbol_gate": ("breadth_gate_symbol", "breadth_gate_mode", "breadth_gate_len"),
    "use_vola_compression_gate": (
        "vola_baseline_len", "compression_ratio_max", "compression_recent_bars",
        "expansion_range_mult", "require_expansion_on_confirm_or_ready",
    ),
    "use_accel_module": (
        "accel_len_fast", "accel_len_mid1", "accel_len_mid2", "accel_len_slow",
        "accel_smooth_len", "accel_cross_threshold", "accel_integration_mode",
        "require_accel_above_zero_for_ready", "accel_recent_cross_bars",
        "accel_close_safe_only", "accel_use_for_ready",
        "accel_use_for_entry_best", "accel_use_for_entry_strict",
    ),
    "use_sd_confluence": (
        "sd_lr_len", "sd_smooth_len", "sd_pivot_len", "sd_recent_window",
        "sd_higher_low_steps_required", "sd_require_for_armed",
        "sd_require_for_confirmed", "sd_require_for_ready",
        "sd_require_for_entry_best", "sd_require_both_for_entry_strict",
        "sd_require_osc_rising_for_ready",
    ),
    "use_volatility_regime": (
        "vol_ma_mode", "vol_ma_len_1", "vol_ma_len_2", "vol_ma_len_3", "vol_ma_len_4",
        "vol_require_all_stack_slopes", "vol_bb_len", "vol_bb_mult", "vol_kc_len",
        "vol_kc_mult", "vol_squeeze_recent_bars", "vol_release_recent_bars",
        "vol_momentum_len", "vol_momentum_smooth", "vol_require_squeeze_for_watchlist",
        "vol_require_squeeze_for_ready", "vol_require_release_for_entry_best",
        "vol_require_release_for_entry_strict",
    ),
    "use_stretch_context": (
        "stretch_len", "lower_extreme_z", "lower_extreme_recent_bars",
        "anti_chase_max_z_ready", "anti_chase_max_z_best", "anti_chase_max_z_strict",
        "stretch_require_lower_extreme_for_ready",
        "stretch_require_lower_extreme_for_entry_best",
        "stretch_require_lower_extreme_for_entry_strict",
    ),
    "use_ddvi_context": (
        "ddvi_di_length", "ddvi_advx_smooth", "ddvi_ma_select", "ddvi_ma_len",
        "ddvi_bb_ma_select", "ddvi_bb_len", "ddvi_bb_mult",
        "ddvi_lower_extreme_lookback", "use_ddvi_hidden_bull", "use_ddvi_strong_bull",
        "ddvi_pivot_left", "ddvi_pivot_right", "ddvi_div_min_range",
        "ddvi_div_max_range", "ddvi_eq_zone_len", "ddvi_eq_zone_atr_mult",
        "ddvi_eq_zone_dev_mult", "ddvi_close_safe_only",
    ),
    "show_Structure": ("show_bull",),
    "show_ob": ("bull_ob_css", "bull_ob_css_line", "ob_showlast"),
    "ob_keep_broken": ("ob_keep_broken_max", "bull_ob_css_broken"),
    "show_fvg": ("fvg_showlast", "bull_fvg_css", "bull_fvg_line_css"),
    "fvg_keep_filled": ("fvg_keep_filled_max", "bull_fvg_css_filled"),
    "filter_insignificant_fvgs": ("min_fvg_size_atr_len", "min_fvg_size_atr_mult"),
    "use_microstructure_profiles": (
        "micro_midday_block_session", "micro_premarket_session",
        "micro_afterhours_session", "micro_stop_hunt_ob_sweep_depth",
        "micro_stop_hunt_fvg_sweep_depth", "micro_stop_hunt_relvol_min",
        "micro_stop_hunt_invalidation_atr", "micro_stop_hunt_force_close_confirm",
        "micro_stop_hunt_disable_live_invalid", "micro_fast_decay_setup_age_max",
        "micro_fast_decay_confirm_age_max",
    ),
    "use_adx": ("adx_len", "adx_trend_min", "adx_strong_min"),
    "use_rel_volume": ("relvol_len", "relvol_good"),
    "use_strong_close_filter": ("min_close_in_range_pct",),
    "show_long_engine_debug": ("long_engine_debug_mode",),
    "allow_armed_source_upgrade": ("min_source_upgrade_quality_gain",),
    "use_context_quality_score": ("min_context_quality_score",),
    "enable_trend_tf_0": ("mtf_trend_tf0",),
}


def _decl_lines() -> dict[str, tuple[int, str]]:
    """varname -> (lineno, line) for every input declaration in the Suite."""
    pattern = re.compile(
        r"^\s*(?:var\s+[A-Za-z_][\w.]*\s+|var\s+)?(?P<name>[A-Za-z_]\w*)\s*=\s*input"
    )
    result: dict[str, tuple[int, str]] = {}
    for lineno, line in enumerate(
        _SUITE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = pattern.match(line)
        if match:
            result[match.group("name")] = (lineno, line)
    return result


_ACTIVE_RE = re.compile(r"active\s*=\s*(?P<master>[A-Za-z_]\w*)")


def _active_arg(line: str) -> str | None:
    # Only the argument list before any tooltip text counts — tooltips are
    # prose and may legitimately contain the word sequence "active = ".
    head = line.split("tooltip")[0]
    match = _ACTIVE_RE.search(head)
    return match.group("master") if match else None


@pytest.mark.parametrize(
    ("master", "dependent"),
    [(m, d) for m, deps in _WIRING.items() for d in deps],
)
def test_dependent_is_wired_to_its_master(master: str, dependent: str) -> None:
    decls = _decl_lines()
    assert dependent in decls, f"{dependent} has no input declaration"
    assert master in decls, f"{master} has no input declaration"
    assert _active_arg(decls[dependent][1]) == master
    # Pine evaluates top-down: a master declared after its dependent is a
    # compile error on TradingView, which only the save chain would catch.
    assert decls[master][0] < decls[dependent][0]


def test_masters_are_never_greyed_themselves() -> None:
    decls = _decl_lines()
    greyed = [m for m in _WIRING if _active_arg(decls[m][1]) is not None]
    assert greyed == []


def test_wiring_ledger_covers_every_active_use() -> None:
    """Population check: every active= in the file is in _WIRING, and vice versa."""
    wired = {(m, d) for m, deps in _WIRING.items() for d in deps}
    observed = {
        (master, name)
        for name, (_, line) in _decl_lines().items()
        if (master := _active_arg(line)) is not None
    }
    assert observed == wired, (
        f"only in file: {sorted(observed - wired)[:5]} — "
        f"only in ledger: {sorted(wired - observed)[:5]}"
    )
    assert len(wired) == 125
