"""Root Pine surfaces — the `active =` master→dependent wiring ledger.

Pine's July-2025 ``active`` input parameter greys dependent inputs while
their master toggle is off. This ledger freezes WHICH inputs hang on WHICH
master, deliberately conservative: engine parameters that act regardless of
a display toggle (swing_length, EMA lengths, score weights) and multi-master
cases (vwap_session, market EMA lengths) are NOT wired, and masters are
never greyed by anything. A new wired input extends _WIRING in the same
commit — the completeness test measures the WHOLE file, not a sample.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

_SUITE_WIRING: dict[str, tuple[str, ...]] = {
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


# Rollout 2026-08-16, after the exemplar's green deploy (save run 31952519241:
# 12/12 saved, re-applied, 131 bindings repaired): the siblings carry far
# fewer parameter dependencies than the Suite — most of their inputs are BUS
# bindings (NEVER greyed: the binding writer keys on the combobox text) or
# engine parameters. SMC_Hold_Manager is deliberately absent: its build-3
# source is CONTRACT-FROZEN (five evidence guards pin the sha256 in
# artifacts/governance/smc_hold_manager_shadow_contract.json) — wiring it
# from outside would mint a foreign build in that lane's evidence chain.
# The tripwire test at the bottom fires when the lane mints build 4.
_WIRING_BY_FILE: dict[str, dict[str, tuple[str, ...]]] = {
    "SMC_Long_Dip_Suite.pine": _SUITE_WIRING,
    "SMC_Long_Dip_Dashboard.pine": {
        "tm_enable": ("tm_tp1_r", "tm_tp2_r", "tm_be_after_t1"),
    },
    "SMC_Long_Dip_Mobile.pine": {
        "tm_enable": ("tm_tp1_r", "tm_tp2_r", "tm_be_after_t1"),
    },
    "SMC_Long_Dip_Strategy.pine": {
        "use_take_profit": ("take_profit_r",),
    },
    "SMC_Breakout_Overlay.pine": {
        "sim_on": ("rr", "atrLen", "atrMult", "sl_on_close", "show_table"),
    },
    # Wired in #4758 (opt-in real footprint delta), ledgered here.
    "SMC_Orderflow_Overlay.pine": {
        "use_real_footprint": (
            "fp_ticks_per_row", "fp_value_area_pct", "fp_imbalance_pct",
        ),
    },
}

_TOTAL_PAIRS = 140  # 125 Suite + 3+3+1+5 rollout + 3 Orderflow (#4758)


def _decl_lines(fname: str) -> dict[str, tuple[int, str]]:
    """varname -> (lineno, line) for every input declaration in ``fname``."""
    pattern = re.compile(
        r"^\s*(?:var\s+)?(?:[A-Za-z_][\w.]*\s+)?(?P<name>[A-Za-z_]\w*)\s*=\s*input"
    )
    result: dict[str, tuple[int, str]] = {}
    for lineno, line in enumerate(
        (_REPO / fname).read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = pattern.match(line)
        if match:
            result[match.group("name")] = (lineno, line)
    return result


# Word boundary on the left: variables named `*_active` (src_zone_active =)
# must not read as the parameter. Master captured on the right.
_ACTIVE_RE = re.compile(r"(?<![A-Za-z0-9_])active\s*=\s*(?P<master>[A-Za-z_]\w*)")
_STRING_RE = re.compile(r"\"[^\"]*\"|'[^']*'")


def _active_arg(line: str) -> str | None:
    # Blank out string literals first: tooltip prose may contain the word
    # sequence "active = ", and the real parameter may sit before OR after
    # the tooltip in the argument list.
    match = _ACTIVE_RE.search(_STRING_RE.sub('""', line))
    return match.group("master") if match else None


@pytest.mark.parametrize(
    ("fname", "master", "dependent"),
    # sorted(): the xdist determinism guard requires an order-stable source
    # so all workers collect identical test IDs.
    sorted(
        (f, m, d)
        for f, wiring in _WIRING_BY_FILE.items()
        for m, deps in wiring.items()
        for d in deps
    ),
)
def test_dependent_is_wired_to_its_master(fname: str, master: str, dependent: str) -> None:
    decls = _decl_lines(fname)
    assert dependent in decls, f"{fname}: {dependent} has no input declaration"
    assert master in decls, f"{fname}: {master} has no input declaration"
    assert _active_arg(decls[dependent][1]) == master
    # Pine evaluates top-down: a master declared after its dependent is a
    # compile error on TradingView, which only the save chain would catch.
    assert decls[master][0] < decls[dependent][0]


@pytest.mark.parametrize("fname", sorted(_WIRING_BY_FILE))
def test_masters_are_never_greyed_themselves(fname: str) -> None:
    decls = _decl_lines(fname)
    greyed = [m for m in _WIRING_BY_FILE[fname] if _active_arg(decls[m][1]) is not None]
    assert greyed == []


def test_wiring_ledger_covers_every_active_use_repo_wide() -> None:
    """Population check over ALL live root/SMC++ Pine files, not a sample.

    A file that gains ``active =`` without a ledger entry — or a ledgered
    pair the file no longer carries — turns red here, so the wiring can
    only evolve deliberately.
    """
    observed: set[tuple[str, str, str]] = set()
    scanned = 0
    for path in sorted(_REPO.glob("*.pine")) + sorted((_REPO / "SMC++").glob("*.pine")):
        fname = str(path.relative_to(_REPO))
        scanned += 1
        for name, (_, line) in _decl_lines(fname).items():
            master = _active_arg(line)
            if master is not None:
                observed.add((fname, master, name))
    wired = {
        (f, m, d)
        for f, wiring in _WIRING_BY_FILE.items()
        for m, deps in wiring.items()
        for d in deps
    }
    assert scanned >= 20, f"only {scanned} files scanned — selection rot?"
    assert observed == wired, (
        f"only in files: {sorted(observed - wired)[:5]} — "
        f"only in ledger: {sorted(wired - observed)[:5]}"
    )
    assert len(wired) == _TOTAL_PAIRS


# -- Hold-Manager tripwire: forward promise mechanised (CLAUDE.md doctrine) --
# Build-3 contract source hash, measured 2026-08-16. The wiring below is
# ANALYSED AND READY (`atr` is defined once and consumed once, by the
# chandelier; `i_tstop_min` gates only the time-stop) but must ride the
# lane's own next build: five evidence guards pin this hash, so wiring from
# outside would mint a foreign build in that chain.
_HOLD_MANAGER_BUILD3_SHA = (
    "88d20484055c850f2a558434aa65b9429e60b9f17373c225d24a931325e82048"
)
_HOLD_MANAGER_PENDING_WIRING: dict[str, tuple[str, ...]] = {
    "i_use_chand": ("i_atr_len", "i_atr_mult"),
    "i_use_tstop": ("i_tstop_min",),
}
_HOLD_MANAGER_CONTRACT = (
    _REPO / "artifacts" / "governance" / "smc_hold_manager_shadow_contract.json"
)


def test_hold_manager_wiring_rides_the_next_build() -> None:
    """Sleeps while the shadow contract still pins build 3; fires on build 4.

    Fire semantics: the Hold-Manager lane minted a new build — take the
    ``active =`` wiring along IN THAT SAME PR (add the three insertions to
    ``SMC_Hold_Manager.pine``, move ``_HOLD_MANAGER_PENDING_WIRING`` into
    ``_WIRING_BY_FILE`` and raise ``_TOTAL_PAIRS`` 140 -> 143), or defer
    DELIBERATELY by updating the frozen hash here with a dated comment.
    """
    contract = json.loads(_HOLD_MANAGER_CONTRACT.read_text(encoding="utf-8"))
    if contract["source"]["sha256"] == _HOLD_MANAGER_BUILD3_SHA:
        assert "SMC_Hold_Manager.pine" not in _WIRING_BY_FILE, (
            "the contract still pins build 3 — wiring now would mint a "
            "foreign build in the shadow lane's evidence chain"
        )
        return
    assert _WIRING_BY_FILE.get("SMC_Hold_Manager.pine") == _HOLD_MANAGER_PENDING_WIRING, (
        "the Hold-Manager lane minted a new build (contract source.sha256 "
        f"moved off build 3): take the active= wiring along in this same PR "
        f"— pairs: {_HOLD_MANAGER_PENDING_WIRING} — move them into "
        "_WIRING_BY_FILE, raise _TOTAL_PAIRS 140 -> 143, and wire the three "
        "insertions in SMC_Hold_Manager.pine; or defer deliberately by "
        "updating _HOLD_MANAGER_BUILD3_SHA with a dated comment."
    )
