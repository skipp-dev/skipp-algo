from __future__ import annotations

import re

from tests.smc_manifest_test_utils import ROOT

UTILS_PATH = ROOT / 'SMC++' / 'smc_utils.pine'
CORE_ENGINE_PATH = ROOT / 'SMC_Core_Engine.pine'


def _read_utils_source() -> str:
    return UTILS_PATH.read_text(encoding='utf-8')


def _read_core_source() -> str:
    return CORE_ENGINE_PATH.read_text(encoding='utf-8')


# ── Library header ──────────────────────────────────────────────────────────


def test_smc_utils_file_exists_and_declares_library() -> None:
    assert UTILS_PATH.exists(), 'SMC++/smc_utils.pine must exist'
    source = _read_utils_source()
    assert 'library("smc_utils", overlay = true)' in source


# ── Embedded helper section marker ─────────────────────────────────────────


def test_embedded_helpers_section_exists() -> None:
    source = _read_utils_source()
    assert '// Embedded helpers (extracted from Core Engine)' in source


# ── smc_lib_atr ─────────────────────────────────────────────────────────────


def test_smc_lib_atr_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_atr(simple int length) =>' in source


def test_smc_lib_atr_uses_ta_atr_and_cumulative_fallback() -> None:
    source = _read_utils_source()
    assert 'float atr_value = ta.atr(length)' in source
    assert 'float tr_cum = ta.cum(ta.tr(true))' in source
    assert 'atr_value := tr_cum / (bar_index + 1)' in source


# ── smc_lib_ehma ────────────────────────────────────────────────────────────


def test_smc_lib_ehma_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_ehma(float source, simple int length) =>' in source


def test_smc_lib_ehma_uses_half_and_sqrt_lengths() -> None:
    source = _read_utils_source()
    assert 'int half_length = math.max(1, int(math.round(length / 2.0)))' in source
    assert 'int sqrt_length = math.max(1, int(math.round(math.sqrt(length))))' in source


# ── smc_lib_thma ────────────────────────────────────────────────────────────


def test_smc_lib_thma_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_thma(float source, simple int length) =>' in source


def test_smc_lib_thma_uses_triple_wma_combination() -> None:
    source = _read_utils_source()
    assert 'int len_sixth = math.max(1, int(math.round(length / 6.0)))' in source
    assert 'int len_quarter = math.max(1, int(math.round(length / 4.0)))' in source
    assert 'int len_half = math.max(1, int(math.round(length / 2.0)))' in source
    assert 'ta.wma(ta.wma(source, len_sixth) * 3 - ta.wma(source, len_quarter) - ta.wma(source, len_half), len_half)' in source


# ── smc_lib_get_ma ──────────────────────────────────────────────────────────


def test_smc_lib_get_ma_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_get_ma(simple ct.SmcLibMovingAverage select_ma = ct.SmcLibMovingAverage.SMA, float source, simple int length) =>' in source


def test_smc_lib_get_ma_switch_covers_all_ma_types() -> None:
    source = _read_utils_source()
    expected_cases = [
        'ct.SmcLibMovingAverage.EMA => ta.ema(source, length)',
        'ct.SmcLibMovingAverage.RMA => ta.rma(source, length)',
        'ct.SmcLibMovingAverage.WMA => ta.wma(source, length)',
        'ct.SmcLibMovingAverage.VWMA => ta.vwma(source, length)',
        'ct.SmcLibMovingAverage.HMA => ta.hma(source, length)',
        'ct.SmcLibMovingAverage.EHMA => smc_lib_ehma(source, length)',
        'ct.SmcLibMovingAverage.THMA => smc_lib_thma(source, length)',
        '=> ta.sma(source, length)',
    ]
    for case in expected_cases:
        assert case in source, f'smc_lib_get_ma missing switch case: {case}'


# ── smc_lib_bb ──────────────────────────────────────────────────────────────


def test_smc_lib_bb_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_bb(float source, simple int length, float mult, simple ct.SmcLibMovingAverage select_ma) =>' in source


def test_smc_lib_bb_delegates_to_get_ma() -> None:
    source = _read_utils_source()
    assert 'float base = smc_lib_get_ma(select_ma, source, length)' in source
    assert 'float dev = mult * ta.stdev(source, length)' in source
    assert '[base, base + dev, base - dev]' in source


# ── smc_lib_dmi ─────────────────────────────────────────────────────────────


def test_smc_lib_dmi_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_dmi(simple int di_length = 17, simple int adx_smoothing = 14) =>' in source


def test_smc_lib_dmi_delegates_to_ta_dmi() -> None:
    source = _read_utils_source()
    assert 'ta.dmi(di_length, adx_smoothing)' in source


# ── smc_lib_detect_divergence ───────────────────────────────────────────────


def test_smc_lib_detect_divergence_is_exported() -> None:
    source = _read_utils_source()
    assert 'export smc_lib_detect_divergence(float osc, simple int pivot_confirmation_bars_left = 5, simple int pivot_confirmation_bars_right = 3, simple int pivot_min_x_distance = 5, simple int pivot_max_x_distance = 50, series float ref_low = low, series float ref_high = high, simple int pivot_min_y_distance_len = 14, simple float pivot_min_y_distance_dev_mult = 0.1, simple float pivot_min_y_distance_atr_mult = 0.1) =>' in source


def test_smc_lib_detect_divergence_returns_10_element_tuple() -> None:
    source = _read_utils_source()
    assert '[strong_bull, strong_bear, medium_bull, medium_bear, weak_bull, weak_bear, hidden_bull, hidden_bear, osc_pivot_h, osc_pivot_l]' in source
    assert '[false, false, false, false, false, false, false, false, osc_pivot_h, osc_pivot_l]' in source


def test_smc_lib_detect_divergence_uses_pivot_detection() -> None:
    source = _read_utils_source()
    assert 'bool osc_pivot_l = not na(ta.pivotlow(osc, pivot_confirmation_bars_left, pivot_confirmation_bars_right))' in source
    assert 'bool osc_pivot_h = not na(ta.pivothigh(osc, pivot_confirmation_bars_left, pivot_confirmation_bars_right))' in source


def test_smc_lib_detect_divergence_calls_smc_lib_atr_internally() -> None:
    source = _read_utils_source()
    assert 'float price_atr_value = smc_lib_atr(pivot_min_y_distance_len) * pivot_min_y_distance_atr_mult' in source


# ── All 8 helpers are exported ──────────────────────────────────────────────


def test_all_embedded_helpers_are_exported() -> None:
    source = _read_utils_source()

    helpers = [
        'export smc_lib_atr(',
        'export smc_lib_ehma(',
        'export smc_lib_thma(',
        # 2026-06-11 (trend-state features): ZLEMA MA type added.
        'export smc_lib_zlema(',
        'export smc_lib_get_ma(',
        'export smc_lib_bb(',
        'export smc_lib_dmi(',
        'export smc_lib_detect_divergence(',
    ]
    for helper in helpers:
        assert helper in source, f'Missing embedded helper export: {helper}'


def test_no_unexpected_smc_lib_exports() -> None:
    source = _read_utils_source()

    smc_lib_exports = re.findall(r'^export\s+smc_lib_\w+\(', source, re.MULTILINE)
    # 2026-06-11 (trend-state features): 7 → 8, smc_lib_zlema added.
    assert len(smc_lib_exports) == 8, (
        f'Expected exactly 8 smc_lib_ exports, found {len(smc_lib_exports)}: {smc_lib_exports}'
    )


# ── Core Engine import and consumption ──────────────────────────────────────


def test_core_engine_imports_smc_utils_as_u() -> None:
    source = _read_core_source()
    assert 'import preuss_steffen/smc_utils/1 as u' in source


def test_core_engine_uses_smc_lib_atr_via_u() -> None:
    source = _read_core_source()
    assert 'u.smc_lib_atr(' in source


def test_core_engine_uses_smc_lib_dmi_via_u() -> None:
    source = _read_core_source()
    assert 'u.smc_lib_dmi(' in source


def test_core_engine_uses_smc_lib_get_ma_via_u() -> None:
    source = _read_core_source()
    assert 'u.smc_lib_get_ma(' in source


def test_core_engine_uses_smc_lib_bb_via_u() -> None:
    source = _read_core_source()
    assert 'u.smc_lib_bb(' in source


def test_core_engine_uses_smc_lib_detect_divergence_via_u() -> None:
    source = _read_core_source()
    assert 'u.smc_lib_detect_divergence(' in source


# ── No duplicates: helpers extracted, not copied ────────────────────────────


def test_core_engine_has_no_local_smc_lib_atr_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_atr(simple int length) =>' not in source


def test_core_engine_has_no_local_smc_lib_ehma_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_ehma(float source, simple int length) =>' not in source


def test_core_engine_has_no_local_smc_lib_thma_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_thma(float source, simple int length) =>' not in source


def test_core_engine_has_no_local_smc_lib_get_ma_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_get_ma(' not in source.replace('u.smc_lib_get_ma(', '')


def test_core_engine_has_no_local_smc_lib_bb_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_bb(' not in source.replace('u.smc_lib_bb(', '')


def test_core_engine_has_no_local_smc_lib_dmi_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_dmi(' not in source.replace('u.smc_lib_dmi(', '')


def test_core_engine_has_no_local_smc_lib_detect_divergence_definition() -> None:
    source = _read_core_source()
    assert 'smc_lib_detect_divergence(' not in source.replace('u.smc_lib_detect_divergence(', '')
