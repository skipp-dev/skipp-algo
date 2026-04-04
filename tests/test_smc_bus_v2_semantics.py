from __future__ import annotations

import pathlib
import re

from tests.smc_manifest_test_utils import ROOT, load_manifest


CORE_PATH = ROOT / 'SMC_Core_Engine.pine'
DASHBOARD_PATH = ROOT / 'SMC_Dashboard.pine'
STRATEGY_PATH = ROOT / 'SMC_Long_Strategy.pine'


MANIFEST = load_manifest()
LEGACY_CORE_CHANNELS = list(MANIFEST.ENGINE_BUS_LABELS[:10])
STRATEGY_CHANNELS = list(MANIFEST.STRATEGY_BUS_LABELS)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding = 'utf-8')


def pack_bus_row(row_state: int, reason_code: int) -> int:
    return (row_state + 1) * 100 + reason_code


def pack_bus_four(value1: int, value2: int, value3: int, value4: int) -> int:
    return value1 * 1_000_000_000 + value2 * 1_000_000 + value3 * 1_000 + value4


def pack_slot(packed_value: int, slot: int) -> int:
    if slot == 0:
        return packed_value // 1_000_000_000
    if slot == 1:
        return (packed_value // 1_000_000) % 1000
    if slot == 2:
        return (packed_value // 1_000) % 1000
    return packed_value % 1000


def pack_bus_counts(primary_count: int, secondary_count: int) -> int:
    return primary_count * 1_000_000 + secondary_count


def count_pack_slot(packed_value: int, slot: int) -> int:
    if slot == 0:
        return packed_value // 1_000_000
    return packed_value % 1_000_000


def row_status(row_code: int) -> int:
    return row_code // 100 - 1


def row_reason(row_code: int) -> int:
    return row_code % 100


def resolve_objects_row_code(ob_count: int, fvg_count: int) -> int:
    if ob_count > 0 and fvg_count > 0:
        return pack_bus_row(5, 3)
    if ob_count > 0:
        return pack_bus_row(3, 1)
    if fvg_count > 0:
        return pack_bus_row(3, 2)
    return pack_bus_row(0, 4)


def debug_engine_enabled(row_code: int) -> bool:
    return (row_reason(row_code) // 4) % 2 == 1


def resolve_debug_state_row_code(
    debug_flags_row_code: int,
    state_code: int,
    armed_state: bool,
    confirmed_state: bool,
    ready_state: bool,
) -> int:
    if not debug_engine_enabled(debug_flags_row_code):
        return pack_bus_row(0, 0)
    if state_code == -1:
        return pack_bus_row(-1, 2)
    if armed_state or confirmed_state or ready_state:
        return pack_bus_row(5, 3)
    return pack_bus_row(2, 4)


def normalize_bus_trend(direction: int) -> int:
    return 2 if direction > 0 else 0 if direction < 0 else 1


def pack_bus_trend_set(trend_now: int, trend_htf_1: int, trend_htf_2: int, trend_htf_3: int) -> int:
    return (
        normalize_bus_trend(trend_now) * 1000
        + normalize_bus_trend(trend_htf_1) * 100
        + normalize_bus_trend(trend_htf_2) * 10
        + normalize_bus_trend(trend_htf_3)
    )


def trend_slot(packed_value: int, slot: int) -> int:
    if slot == 0:
        return (packed_value // 1000) % 10
    if slot == 1:
        return (packed_value // 100) % 10
    if slot == 2:
        return (packed_value // 10) % 10
    return packed_value % 10


def pack_bus_meta(freshness_code: int, source_state_code: int, reclaim_code: int, zone_code: int) -> int:
    return freshness_code * 1000 + source_state_code * 100 + reclaim_code * 10 + zone_code


def meta_slot(packed_value: int, slot: int) -> int:
    if slot == 0:
        return (packed_value // 1000) % 10
    if slot == 1:
        return (packed_value // 100) % 10
    if slot == 2:
        return (packed_value // 10) % 10
    return packed_value % 10


def source_kind_text(source_code: int) -> str:
    return {
        1: 'OB',
        2: 'FVG',
        3: 'Swing Low',
        4: 'Internal Low',
    }.get(source_code, 'None')


def freshness_text(freshness_code: int) -> str:
    return {
        1: 'confirm fresh',
        2: 'confirm stale',
        3: 'armed fresh',
        4: 'armed stale',
    }.get(freshness_code, 'n/a')


def source_state_text(source_state_code: int) -> str:
    return {
        1: 'source alive',
        2: 'source invalid',
        3: 'source lost',
    }.get(source_state_code, 'n/a')


def zone_reason_text(zone_code: int) -> str:
    return {
        1: 'Zone touched',
        2: 'In FVG Zone',
        3: 'In OB Zone',
        4: 'In OB + FVG Zone',
    }.get(zone_code, 'No Long Zone')


def long_visual_text(state_code: int) -> str:
    if state_code == -1:
        return 'Fail'
    if state_code == 1:
        return 'In Zone'
    if state_code == 2:
        return 'Armed'
    if state_code == 3:
        return 'Building'
    if state_code == 4:
        return 'Confirmed'
    if state_code >= 5:
        return 'Ready'
    return 'Neutral'


def exec_tier_text(state_code: int) -> str:
    if state_code >= 7:
        return 'Strict'
    if state_code == 6:
        return 'Best'
    if state_code == 5:
        return 'Ready'
    if state_code == 4:
        return 'Confirmed'
    if state_code in {2, 3}:
        return 'Armed'
    if state_code == 1:
        return 'Watchlist'
    return 'n/a'


def setup_text(state_code: int, source_code: int) -> str:
    source_text = source_kind_text(source_code)
    if state_code == -1:
        return 'Invalidated'
    if state_code == 1:
        return 'In Zone'
    if state_code == 2:
        return f'Armed | {source_text}'
    if state_code == 3:
        return f'Building | {source_text}'
    if state_code == 4:
        return f'Confirmed | {source_text}'
    if state_code == 5:
        return f'Ready | {source_text}'
    if state_code == 6:
        return f'Entry Best | {source_text}'
    if state_code >= 7:
        return f'Entry Strict | {source_text}'
    return 'No Setup'


def setup_age_text(state_code: int, freshness_code: int) -> str:
    if state_code >= 4:
        return freshness_text(freshness_code)
    if state_code in {2, 3}:
        return freshness_text(freshness_code)
    return 'n/a'


def decode_session_text(row_code: int) -> str:
    reason_code = row_reason(row_code)
    if reason_code == 1:
        return 'OK' if row_status(row_code) == 5 else 'n/a'
    if reason_code == 2:
        return 'off'
    if reason_code == 3:
        return 'Entry session blocked'
    return 'OR blocked'


def decode_market_text(row_code: int) -> str:
    reason_code = row_reason(row_code)
    if reason_code == 1:
        return 'OK' if row_status(row_code) == 5 else 'off'
    if reason_code == 2:
        return 'Missing symbol'
    if reason_code == 3:
        return 'Index blocked'
    if reason_code == 4:
        return 'Sector blocked'
    return 'Breadth blocked'


def decode_vola_text(row_code: int) -> str:
    reason_code = row_reason(row_code)
    if reason_code == 1:
        return 'off' if row_status(row_code) == 0 else 'OK'
    if reason_code == 2:
        return 'Compression -> Expansion'
    if reason_code == 3:
        return 'Compression context'
    return 'Blocked'


def decode_micro_session_text(row_code: int) -> str:
    reason_code = row_reason(row_code)
    if reason_code == 1:
        return 'off' if row_status(row_code) == 0 else 'OK'
    if reason_code == 2:
        return 'RTH only'
    if reason_code == 3:
        return 'Midday block'
    if reason_code == 4:
        return 'Weak premarket'
    return 'Weak after-hours'


def decode_micro_fresh_text(row_code: int, freshness_code: int, source_state_code: int) -> str:
    if row_reason(row_code) == 1 and row_status(row_code) == 0:
        return 'off'
    return f'{freshness_text(freshness_code)} | {source_state_text(source_state_code)}'


def decode_volume_data_text(row_code: int) -> str:
    reason_code = row_reason(row_code)
    if reason_code == 1:
        return 'OK'
    if reason_code == 2:
        return 'Weak feed quality'
    if reason_code == 3:
        return 'Chart OK | LTF no-vol'
    if reason_code == 4:
        return 'Price-only LTF'
    return 'No current bar volume'


def quality_bounds(score_value: float, bounds_pack: int) -> tuple[int, int, str]:
    min_score = bounds_pack // 1000
    max_score = bounds_pack % 1000
    return min_score, max_score, f'{score_value:.2f}'.rstrip('0').rstrip('.') + f'/{max_score} | min {min_score}'


def test_original_10_core_channels_remain_present_in_order() -> None:
    source = _read(CORE_PATH)
    plot_labels = re.findall(r"'([^']+)'", '\n'.join(re.findall(r"plot\([^\n]+display\s*=\s*display\.none\)", source)))

    assert plot_labels[:10] == LEGACY_CORE_CHANNELS
    assert 'plot(long_state.armed ? 1.0 : 0.0, \'BUS Armed\'' in source
    assert 'plot(long_state.confirmed ? 1.0 : 0.0, \'BUS Confirmed\'' in source
    assert 'plot(long_ready_state ? 1.0 : 0.0, \'BUS Ready\'' in source
    assert 'plot(long_entry_best_state ? 1.0 : 0.0, \'BUS EntryBest\'' in source
    assert 'plot(long_entry_strict_state ? 1.0 : 0.0, \'BUS EntryStrict\'' in source
    assert 'plot(bus_trigger_level, \'BUS Trigger\'' in source
    assert 'plot(bus_invalidation_level, \'BUS Invalidation\'' in source
    assert 'plot(lib_sq_score, \'BUS QualityScore\'' in source


def test_strategy_contract_channels_remain_unchanged() -> None:
    strategy_source = _read(STRATEGY_PATH)
    bound_labels = re.findall(r'input\.source\(close,\s*"([^"]+)"', strategy_source)

    assert bound_labels == STRATEGY_CHANNELS
    assert 'bool risk_levels_ok = not na(src_trigger) and not na(src_invalidation) and src_trigger > src_invalidation' in strategy_source
    assert 'bool quality_ok = na(src_quality_score) ? false : src_quality_score >= min_quality_score' in strategy_source
    assert 'strategy.entry("L", strategy.long, stop = src_trigger)' in strategy_source
    assert 'var float active_invalidation = na' in strategy_source
    assert 'strategy.exit("L Exit", "L", stop = exit_stop, limit = exit_limit)' in strategy_source


def test_row_pack_and_unpack_contract_round_trips_consistently() -> None:
    core_source = _read(CORE_PATH)
    dashboard_source = _read(DASHBOARD_PATH)

    assert 'float((row_state + 1) * 100 + reason_code)' in core_source
    assert 'value1 * 1000000000.0 + value2 * 1000000.0 + value3 * 1000.0 + value4' in core_source
    assert 'int(math.floor(row_code / 100)) - 1' in dashboard_source
    assert 'row_code % 100' in dashboard_source

    row_a = pack_bus_row(5, 1)
    row_b = pack_bus_row(-1, 3)
    row_c = pack_bus_row(0, 2)
    row_d = pack_bus_row(4, 5)
    packed = pack_bus_four(row_a, row_b, row_c, row_d)

    assert pack_slot(packed, 0) == row_a
    assert pack_slot(packed, 1) == row_b
    assert pack_slot(packed, 2) == row_c
    assert pack_slot(packed, 3) == row_d
    assert row_status(row_a) == 5
    assert row_status(row_b) == -1
    assert row_status(row_c) == 0
    assert row_reason(row_d) == 5


def test_object_count_pack_and_module_pack_c_split_round_trip_consistently() -> None:
    core_source = _read(CORE_PATH)
    dashboard_source = _read(DASHBOARD_PATH)

    assert 'pack_bus_counts(int primary_count, int secondary_count) =>' in core_source
    assert 'count_pack_slot(float packed_value, int slot) =>' in dashboard_source
    assert 'resolve_bus_module_pack_c(bool show_dashboard_ltf_eff, bool ltf_sampling_active, bool ltf_price_only, float ltf_volume_delta, bool use_microstructure_profiles, string micro_profile_text, string micro_modifier_text) =>' in core_source
    assert 'int ltf_delta_row_code = pack_slot(src_module_pack_c, 0)' in dashboard_source
    assert 'int micro_profile_row_code = pack_slot(src_module_pack_c, 3)' in dashboard_source
    assert 'pack_slot(src_module_pack_c, 1)' not in dashboard_source
    assert 'pack_slot(src_module_pack_c, 2)' not in dashboard_source
    assert 'int swing_row_code = int(math.round(nz(src_swing_row, 0.0)))' in dashboard_source
    assert 'int objects_row_code = resolve_objects_row_code(objects_ob_count, objects_fvg_count)' in dashboard_source

    packed_counts = pack_bus_counts(3, 2)
    assert count_pack_slot(packed_counts, 0) == 3
    assert count_pack_slot(packed_counts, 1) == 2
    assert resolve_objects_row_code(3, 2) == pack_bus_row(5, 3)
    assert resolve_objects_row_code(3, 0) == pack_bus_row(3, 1)
    assert resolve_objects_row_code(0, 2) == pack_bus_row(3, 2)
    assert resolve_objects_row_code(0, 0) == pack_bus_row(0, 4)


def test_debug_state_row_reconstructs_locally_from_flags_and_lifecycle_contract() -> None:
    dashboard_source = _read(DASHBOARD_PATH)

    assert 'debug_engine_enabled(int row_code) =>' in dashboard_source
    assert 'resolve_debug_state_row_code(int debug_flags_row_code, int state_code, bool armed_state, bool confirmed_state, bool ready_state) =>' in dashboard_source
    assert 'src_debug_state_row = input.source(close, "BUS DebugStateRow"' not in dashboard_source
    assert 'int debug_state_row_code = resolve_debug_state_row_code(debug_flags_row_code, state_code, armed, confirmed, ready)' in dashboard_source

    debug_engine_off = pack_bus_row(0, 0)
    debug_engine_on = pack_bus_row(5, 4)

    assert resolve_debug_state_row_code(debug_engine_off, 0, False, False, False) == pack_bus_row(0, 0)
    assert resolve_debug_state_row_code(debug_engine_on, -1, False, False, False) == pack_bus_row(-1, 2)
    assert resolve_debug_state_row_code(debug_engine_on, 2, False, False, False) == pack_bus_row(2, 4)
    assert resolve_debug_state_row_code(debug_engine_on, 2, True, False, False) == pack_bus_row(5, 3)
    assert resolve_debug_state_row_code(debug_engine_on, 4, False, True, False) == pack_bus_row(5, 3)
    assert resolve_debug_state_row_code(debug_engine_on, 5, False, False, True) == pack_bus_row(5, 3)


def test_trend_and_meta_packs_round_trip_consistently() -> None:
    core_source = _read(CORE_PATH)
    dashboard_source = _read(DASHBOARD_PATH)

    assert 'dir > 0 ? 2 : dir < 0 ? 0 : 1' in core_source
    assert 'float(normalize_bus_trend(trend_now) * 1000 + normalize_bus_trend(trend_htf_1) * 100 + normalize_bus_trend(trend_htf_2) * 10 + normalize_bus_trend(trend_htf_3))' in core_source
    assert 'float(freshness_code * 1000 + source_state_code * 100 + reclaim_code * 10 + zone_code)' in core_source
    assert 'int(math.floor(packed / 1000)) % 10' in dashboard_source

    packed_trends = pack_bus_trend_set(1, -1, 0, 1)
    assert trend_slot(packed_trends, 0) == 2
    assert trend_slot(packed_trends, 1) == 0
    assert trend_slot(packed_trends, 2) == 1
    assert trend_slot(packed_trends, 3) == 2

    packed_meta = pack_bus_meta(1, 3, 5, 4)
    assert meta_slot(packed_meta, 0) == 1
    assert meta_slot(packed_meta, 1) == 3
    assert meta_slot(packed_meta, 2) == 5
    assert meta_slot(packed_meta, 3) == 4


def test_lifecycle_rows_reconstruct_from_state_and_meta_contract() -> None:
    dashboard_source = _read(DASHBOARD_PATH)

    assert 'dashboard_row(smc_dashboard, 6, "Long Setup", setup_text(state_code, source_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 7, "Setup Age", setup_age_text(state_code, freshness_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 8, "Long Visual", long_visual_text(state_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 9, "Exec Tier", exec_tier_text(state_code)' in dashboard_source

    assert setup_text(7, 1) == 'Entry Strict | OB'
    assert setup_text(6, 2) == 'Entry Best | FVG'
    assert setup_text(4, 3) == 'Confirmed | Swing Low'
    assert setup_text(-1, 0) == 'Invalidated'
    assert zone_reason_text(4) == 'In OB + FVG Zone'
    assert long_visual_text(-1) == 'Fail'
    assert long_visual_text(5) == 'Ready'
    assert exec_tier_text(7) == 'Strict'
    assert exec_tier_text(1) == 'Watchlist'
    assert setup_age_text(4, 1) == 'confirm fresh'
    assert setup_age_text(2, 4) == 'armed stale'


def test_hard_gate_decoders_reproduce_current_bus_v2_contract() -> None:
    dashboard_source = _read(DASHBOARD_PATH)

    assert 'dashboard_row(smc_dashboard, 19, "Session", decode_session_text(session_row_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 20, "Market Gate", decode_market_text(market_row_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 21, "Vola Regime", decode_vola_text(vola_row_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 22, "Micro Session", decode_micro_session_text(micro_session_row_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 23, "Micro Fresh", decode_micro_fresh_text(micro_fresh_row_code, freshness_code, source_state_code)' in dashboard_source
    assert 'dashboard_row(smc_dashboard, 24, "Volume Data", decode_volume_data_text(volume_data_row_code)' in dashboard_source

    assert decode_session_text(pack_bus_row(0, 1)) == 'n/a'
    assert decode_session_text(pack_bus_row(0, 2)) == 'off'
    assert decode_session_text(pack_bus_row(5, 1)) == 'OK'
    assert decode_session_text(pack_bus_row(-1, 3)) == 'Entry session blocked'
    assert decode_session_text(pack_bus_row(-1, 4)) == 'OR blocked'

    assert decode_market_text(pack_bus_row(5, 1)) == 'OK'
    assert decode_market_text(pack_bus_row(-1, 2)) == 'Missing symbol'
    assert decode_market_text(pack_bus_row(-1, 3)) == 'Index blocked'
    assert decode_market_text(pack_bus_row(-1, 4)) == 'Sector blocked'
    assert decode_market_text(pack_bus_row(-1, 5)) == 'Breadth blocked'

    assert decode_vola_text(pack_bus_row(0, 1)) == 'off'
    assert decode_vola_text(pack_bus_row(5, 2)) == 'Compression -> Expansion'
    assert decode_vola_text(pack_bus_row(3, 3)) == 'Compression context'
    assert decode_vola_text(pack_bus_row(-1, 4)) == 'Blocked'

    assert decode_micro_session_text(pack_bus_row(0, 1)) == 'off'
    assert decode_micro_session_text(pack_bus_row(5, 1)) == 'OK'
    assert decode_micro_session_text(pack_bus_row(-1, 2)) == 'RTH only'
    assert decode_micro_session_text(pack_bus_row(-1, 3)) == 'Midday block'
    assert decode_micro_session_text(pack_bus_row(-1, 4)) == 'Weak premarket'

    assert decode_micro_fresh_text(pack_bus_row(0, 1), 1, 1) == 'off'
    assert decode_micro_fresh_text(pack_bus_row(5, 2), 1, 3) == 'confirm fresh | source lost'

    assert decode_volume_data_text(pack_bus_row(5, 1)) == 'OK'
    assert decode_volume_data_text(pack_bus_row(2, 2)) == 'Weak feed quality'
    assert decode_volume_data_text(pack_bus_row(2, 3)) == 'Chart OK | LTF no-vol'
    assert decode_volume_data_text(pack_bus_row(2, 4)) == 'Price-only LTF'
    assert decode_volume_data_text(pack_bus_row(-1, 5)) == 'No current bar volume'


def test_quality_bounds_pack_remains_logically_consistent_with_quality_score() -> None:
    core_source = _read(CORE_PATH)
    dashboard_source = _read(DASHBOARD_PATH)

    assert "plot(resolve_bus_quality_bounds_pack(25, 100), 'BUS QualityBoundsPack'" in core_source
    assert 'quality_bounds_text(float score_value, float bounds_pack) =>' in dashboard_source
    assert 'int min_score = int(math.floor(packed / 1000))' in dashboard_source
    assert 'int max_score = packed % 1000' in dashboard_source
    assert 'str.tostring(score_value, "#.##") + "/" + str.tostring(max_score) + " | min " + str.tostring(min_score)' in dashboard_source

    min_score, max_score, rendered = quality_bounds(74.0, 25_100)
    assert min_score == 25
    assert max_score == 100
    assert rendered == '74/100 | min 25'


def test_dashboard_and_strategy_contracts_share_same_strategy_relevant_channels() -> None:
    core_source = _read(CORE_PATH)
    dashboard_source = _read(DASHBOARD_PATH)
    strategy_source = _read(STRATEGY_PATH)

    for label in STRATEGY_CHANNELS:
        assert f"'{label}'" in core_source
        assert f'"{label}"' in strategy_source

    assert 'src_state_code = input.source(close, "BUS StateCode"' in dashboard_source
    assert 'src_state_code' not in strategy_source
    assert 'src_session_gate_row = input.source(close, "BUS SessionGateRow"' in dashboard_source
    assert 'src_close_strength_row = input.source(close, "BUS CloseStrengthRow"' in dashboard_source
    assert 'src_quality_score_row = input.source(close, "BUS QualityScoreRow"' in dashboard_source
    assert 'src_vol_expand_row = input.source(close, "BUS VolExpandRow"' in dashboard_source
    assert 'src_ddvi_row = input.source(close, "BUS DdviRow"' in dashboard_source
    assert 'src_swing_row = input.source(close, "BUS SwingRow"' in dashboard_source
    assert 'src_ready_gate_row = input.source(close, "BUS ReadyGateRow"' in dashboard_source
    assert 'src_zone_ob_top = input.source(close, "BUS ZoneObTop"' in dashboard_source
    assert 'src_stretch_support_mask = input.source(close, "BUS StretchSupportMask"' in dashboard_source
    assert 'src_ltf_bias_hint = input.source(close, "BUS LtfBiasHint"' in dashboard_source
    assert 'src_objects_count_pack = input.source(close, "BUS ObjectsCountPack"' in dashboard_source
    assert 'src_hard_gates_pack_a' not in dashboard_source
    assert 'src_quality_pack_a' not in dashboard_source
    assert 'src_quality_pack_b' not in dashboard_source
    assert 'src_engine_pack' not in dashboard_source
    assert 'src_module_pack_b' not in dashboard_source
    assert 'HardGatesPackA' not in strategy_source
    assert 'QualityPackA' not in strategy_source
    assert 'QualityPackB' not in strategy_source
    assert 'ModulePackB' not in strategy_source
    assert 'EnginePack' not in strategy_source