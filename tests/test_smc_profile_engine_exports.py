from __future__ import annotations

import re

from tests.smc_manifest_test_utils import ROOT

PROFILE_ENGINE_PATH = ROOT / 'SMC++' / 'smc_profile_engine.pine'
CORE_ENGINE_PATH = ROOT / 'SMC_Core_Engine.pine'


def _read_profile_engine_source() -> str:
    return PROFILE_ENGINE_PATH.read_text(encoding='utf-8')


def _read_core_source() -> str:
    return CORE_ENGINE_PATH.read_text(encoding='utf-8')


# ── Library header ──────────────────────────────────────────────────────────


def test_profile_engine_file_exists_and_declares_library() -> None:
    assert PROFILE_ENGINE_PATH.exists(), 'SMC++/smc_profile_engine.pine must exist'
    source = _read_profile_engine_source()
    assert 'library("smc_profile_engine", overlay = true)' in source


def test_profile_engine_imports_required_dependencies() -> None:
    source = _read_profile_engine_source()
    assert "import preuss_steffen/smc_utils/1 as u" in source
    assert "import preuss_steffen/smc_draw/1 as d" in source


# ── UDT definitions ────────────────────────────────────────────────────────


def test_udt_bucket_is_exported_with_all_fields() -> None:
    source = _read_profile_engine_source()

    assert 'export type Bucket' in source
    for field in [
        'varip int idx',
        'varip float value',
        'varip float top',
        'varip float btm',
        'varip float center',
        'varip float fraction',
    ]:
        assert field in source, f'Bucket field missing: {field}'
    assert 'd.SmcLine plot_bucket_line = na' in source


def test_udt_profile_config_is_exported_with_all_fields() -> None:
    source = _read_profile_engine_source()

    assert 'export type ProfileConfig' in source
    for field in [
        'bool show_poc = true',
        'bool show_profile = false',
        'bool show_va = false',
        'bool show_background = false',
        'bool show_labels = false',
        'bool show_price_levels = false',
        'bool extend = false',
        "string poc_label_text = 'POC'",
        'd.LineArgs args_poc_line = na',
        'd.LineArgs args_vah_line = na',
        'd.LineArgs args_val_line = na',
        'd.LabelArgs args_poc_label = na',
        'd.LineArgs args_profile_line = na',
        'd.BoxArgs args_profile_bg = na',
        'bool initialized = false',
    ]:
        assert field in source, f'ProfileConfig field missing: {field}'


def test_udt_profile_is_exported_with_all_fields() -> None:
    source = _read_profile_engine_source()

    assert 'export type Profile' in source
    for field in [
        'int id',
        'int resolution',
        'float vah_threshold_pc',
        'float val_threshold_pc',
        'varip float[] data_opens',
        'varip float[] data_highs',
        'varip float[] data_lows',
        'varip float[] data_closes',
        'varip float[] data_values',
        'varip float h = na',
        'varip float l = na',
        'varip float total = 0',
        'varip float total_up = 0',
        'varip float total_down = 0',
        'Bucket[] buckets',
        'varip int poc_bucket_index = na',
        'varip int vah_bucket_index = na',
        'varip int val_bucket_index = na',
        'varip float poc = na',
        'varip float vah = na',
        'varip float val = na',
        'd.SmcLine plot_poc = na',
        'd.SmcLine plot_vah = na',
        'd.SmcLine plot_val = na',
        'd.SmcLabel plot_poc_label = na',
        'd.SmcBox plot_profile_bg = na',
        'bool hidden = false',
    ]:
        assert field in source, f'Profile field missing: {field}'


# ── Exported methods ────────────────────────────────────────────────────────


def test_bucket_update_methods_are_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method update(Bucket this, float top, float bottom, float value, float fraction) =>' in source
    assert 'export method update(Bucket this, float value, float fraction) =>' in source


def test_profile_config_init_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method init(ProfileConfig this) =>' in source


def test_profile_apply_style_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method apply_style(Profile this, ProfileConfig args) =>' in source


def test_profile_delete_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method delete(Profile this) =>' in source


def test_profile_hide_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method hide(Profile this) =>' in source


def test_profile_init_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method init(Profile this, bool update_buckets = false) =>' in source


def test_profile_calculate_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method calculate(Profile this, simple int use_open_close_data_for_ranges_shorter_than_bars = 4) =>' in source


def test_profile_update_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method update(Profile this, float[] opens = na, float[] highs = na, float[] lows = na, float[] closes = na, float[] values = na) =>' in source


def test_profile_draw_method_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export method draw(Profile this, ProfileConfig config, int left = na, int right = na, bool extend_only = true, simple bool force_overlay = false, string poc_text_override = na) =>' in source


# ── Exported helper functions ───────────────────────────────────────────────


def test_normalize_profile_resolution_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export normalize_profile_resolution(int resolution) =>' in source


def test_normalize_profile_vah_pc_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export normalize_profile_vah_pc(float vah_pc, float val_pc) =>' in source


def test_normalize_profile_val_pc_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export normalize_profile_val_pc(float vah_pc, float val_pc) =>' in source


def test_profile_data_ready_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export profile_data_ready(float[] highs, float[] lows, float[] values) =>' in source


def test_is_impulse_candle_now_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export is_impulse_candle_now(float candle_body, float impulse_candle_size) =>' in source


def test_is_indecision_candle_now_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export is_indecision_candle_now(float high_now, float low_now, float prior_high, float prior_low, float candle_top_now, float candle_btm_now, float prior_candle_top, float prior_candle_btm, float prior_candle_body, float candle_body, float candle_open, float candle_close) =>' in source


def test_profile_features_enabled_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export profile_features_enabled(bool capture_profile_now, bool align_edge_to_value_area_now, bool align_break_price_to_poc_now) =>' in source


def test_create_profile_is_exported() -> None:
    source = _read_profile_engine_source()

    assert 'export create_profile(float[] opens, float[] highs, float[] lows, float[] closes, float[] values, int resolution = 25, float vah_pc = 80, float val_pc = 20, int idx = bar_index, bool init_calculated = true, simple int use_open_close_data_for_ranges_shorter_than_bars = 4) =>' in source


# ── Export completeness ─────────────────────────────────────────────────────


def test_all_export_declarations_are_accounted_for() -> None:
    source = _read_profile_engine_source()

    export_lines = re.findall(r'^export\s+.*$', source, re.MULTILINE)

    expected_exports = [
        'export type Bucket',
        'export type ProfileConfig',
        'export type Profile',
        'export method update(Bucket this, float top, float bottom, float value, float fraction)',
        'export method update(Bucket this, float value, float fraction)',
        'export method init(ProfileConfig this)',
        'export method apply_style(Profile this, ProfileConfig args)',
        'export method delete(Profile this)',
        'export method hide(Profile this)',
        'export method init(Profile this, bool update_buckets = false)',
        'export method calculate(Profile this, simple int use_open_close_data_for_ranges_shorter_than_bars = 4)',
        'export method update(Profile this, float[] opens = na, float[] highs = na, float[] lows = na, float[] closes = na, float[] values = na)',
        'export method draw(Profile this, ProfileConfig config, int left = na, int right = na, bool extend_only = true, simple bool force_overlay = false, string poc_text_override = na)',
        'export normalize_profile_resolution(int resolution)',
        'export normalize_profile_vah_pc(float vah_pc, float val_pc)',
        'export normalize_profile_val_pc(float vah_pc, float val_pc)',
        'export profile_data_ready(float[] highs, float[] lows, float[] values)',
        'export is_impulse_candle_now(float candle_body, float impulse_candle_size)',
        'export is_indecision_candle_now(float high_now, float low_now, float prior_high, float prior_low, float candle_top_now, float candle_btm_now, float prior_candle_top, float prior_candle_btm, float prior_candle_body, float candle_body, float candle_open, float candle_close)',
        'export profile_features_enabled(bool capture_profile_now, bool align_edge_to_value_area_now, bool align_break_price_to_poc_now)',
        'export create_profile(float[] opens, float[] highs, float[] lows, float[] closes, float[] values, int resolution = 25, float vah_pc = 80, float val_pc = 20, int idx = bar_index, bool init_calculated = true, simple int use_open_close_data_for_ranges_shorter_than_bars = 4)',
    ]

    assert len(export_lines) == len(expected_exports), (
        f'Expected {len(expected_exports)} export declarations, found {len(export_lines)}'
    )

    for expected in expected_exports:
        matched = any(line.startswith(expected) for line in export_lines)
        assert matched, f'Missing export declaration: {expected}'


# ── Core Engine import alias ────────────────────────────────────────────────


def test_core_engine_imports_profile_engine_as_pe() -> None:
    source = _read_core_source()

    assert 'import preuss_steffen/smc_profile_engine/1 as pe' in source


def test_core_engine_uses_pe_profile_type() -> None:
    source = _read_core_source()

    assert 'pe.Profile profile' in source
    assert 'pe.ProfileConfig profile_config' in source


def test_core_engine_uses_pe_create_profile() -> None:
    source = _read_core_source()

    assert 'pe.create_profile(' in source


def test_core_engine_uses_pe_helper_functions() -> None:
    source = _read_core_source()

    assert 'pe.is_impulse_candle_now(' in source
    assert 'pe.is_indecision_candle_now(' in source
    assert 'pe.profile_features_enabled(' in source


def test_core_engine_uses_pe_profile_config_constructor() -> None:
    source = _read_core_source()

    assert 'pe.ProfileConfig.new(' in source
