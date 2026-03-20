from __future__ import annotations


def _model_zone_candidate_preferred(
    candidate_touch_anchor: bool,
    candidate_recency: int | None,
    candidate_quality: float | None,
    candidate_overlap: float | None,
    candidate_id: int | None,
    best_touch_anchor: bool,
    best_recency: int | None,
    best_quality: float | None,
    best_overlap: float | None,
    best_id: int | None,
) -> bool:
    if candidate_touch_anchor != best_touch_anchor:
        return candidate_touch_anchor
    if best_recency is None or candidate_recency != best_recency:
        return best_recency is None or (candidate_recency is not None and candidate_recency > best_recency)
    if best_quality is None or candidate_quality != best_quality:
        return best_quality is None or (candidate_quality is not None and candidate_quality > best_quality)
    if best_overlap is None or candidate_overlap != best_overlap:
        return best_overlap is None or (candidate_overlap is not None and candidate_overlap > best_overlap)
    return best_id is None or (candidate_id is not None and candidate_id > best_id)


def _model_long_invalidation_reason(
    source_broken: bool,
    source_lost: bool,
    setup_expired: bool,
    confirm_expired: bool,
    validation_source: str,
    entry_origin_source: str,
    setup_source_display: str,
) -> str:
    if source_broken:
        return f'{validation_source} source invalidated'
    if source_lost:
        return f'{validation_source} backing zone lost'
    if setup_expired:
        return f'{entry_origin_source} setup expired'
    if confirm_expired:
        return f'{entry_origin_source} confirm expired'
    return setup_source_display


def _model_long_setup_source_display(entry_origin_source: str, validation_source: str) -> str:
    if entry_origin_source == 'None':
        return validation_source
    if validation_source == 'None' or entry_origin_source == validation_source:
        return entry_origin_source
    return f'{entry_origin_source} -> {validation_source}'


def _model_long_ready_states(
    lifecycle_ready_ok: bool,
    setup_hard_gate_ok: bool,
    trade_hard_gate_ok: bool,
    environment_hard_gate_ok: bool,
    quality_gate_ok: bool,
    accel_ready_gate_ok: bool,
    sd_ready_gate_ok: bool,
    vol_ready_context_ok: bool,
    stretch_ready_context_ok: bool,
    ddvi_ready_ok_safe: bool,
    accel_entry_best_gate_ok: bool,
    sd_entry_best_gate_ok: bool,
    vol_entry_best_context_ok_safe: bool,
    stretch_entry_best_context_ok: bool,
    ddvi_entry_best_ok_safe: bool,
    strict_entry_ltf_ok: bool,
    htf_alignment_ok: bool,
    accel_strict_entry_gate_ok: bool,
    sd_entry_strict_gate_ok: bool,
    vol_entry_strict_context_ok_safe: bool,
    stretch_entry_strict_context_ok: bool,
    ddvi_entry_strict_ok_safe: bool,
) -> tuple[bool, bool, bool]:
    long_ready_state = lifecycle_ready_ok and setup_hard_gate_ok and trade_hard_gate_ok and environment_hard_gate_ok and quality_gate_ok and accel_ready_gate_ok and sd_ready_gate_ok and vol_ready_context_ok and stretch_ready_context_ok and ddvi_ready_ok_safe
    long_entry_best_state = long_ready_state and accel_entry_best_gate_ok and sd_entry_best_gate_ok and vol_entry_best_context_ok_safe and stretch_entry_best_context_ok and ddvi_entry_best_ok_safe
    long_entry_strict_state = long_ready_state and strict_entry_ltf_ok and htf_alignment_ok and accel_strict_entry_gate_ok and sd_entry_strict_gate_ok and vol_entry_strict_context_ok_safe and stretch_entry_strict_context_ok and ddvi_entry_strict_ok_safe
    return long_ready_state, long_entry_best_state, long_entry_strict_state


def _model_long_setup_text(
    long_zone_active: bool,
    long_setup_armed: bool,
    long_building_state: bool,
    long_setup_confirmed: bool,
    long_ready_state: bool,
    long_entry_best_state: bool,
    long_entry_strict_state: bool,
    long_setup_source_display: str,
) -> str:
    setup_text = 'No Setup'
    if long_zone_active:
        setup_text = 'In Zone'
    if long_setup_armed:
        setup_text = f'Armed | {long_setup_source_display}'
    if long_building_state:
        setup_text = f'Building | {long_setup_source_display}'
    if long_setup_confirmed:
        setup_text = f'Confirmed | {long_setup_source_display}'
    if long_ready_state:
        setup_text = f'Ready | {long_setup_source_display}'
    if long_entry_best_state:
        setup_text = f'Entry Best | {long_setup_source_display}'
    if long_entry_strict_state:
        setup_text = f'Entry Strict | {long_setup_source_display}'
    return setup_text


def _model_long_visual_state(
    long_zone_active: bool,
    long_setup_armed: bool,
    long_building_state: bool,
    long_setup_confirmed: bool,
    long_ready_state: bool,
    long_entry_best_state: bool,
    long_entry_strict_state: bool,
    long_invalidate_signal: bool,
    invalidated_prior_setup: bool,
    long_invalidated_now: bool,
) -> int:
    visual_state = 0
    if long_zone_active:
        visual_state = 1
    if long_setup_armed:
        visual_state = 2
    if long_building_state:
        visual_state = 3
    if long_setup_confirmed:
        visual_state = 4
    if long_ready_state:
        visual_state = 5
    if long_entry_best_state:
        visual_state = 6
    if long_entry_strict_state:
        visual_state = 7
    if (long_setup_armed or long_setup_confirmed or long_invalidate_signal or invalidated_prior_setup) and long_invalidated_now:
        visual_state = -1
    return visual_state


def _model_long_visual_text(long_visual_state: int) -> str:
    if long_visual_state == -1:
        return 'Blocked'
    if long_visual_state == 0:
        return 'Neutral'
    if long_visual_state == 1:
        return 'In Zone'
    if long_visual_state == 2:
        return 'Armed'
    if long_visual_state == 3:
        return 'Building'
    if long_visual_state == 4:
        return 'Confirmed'
    if long_visual_state == 5:
        return 'Long Ready'
    if long_visual_state == 6:
        return 'Entry Best'
    return 'Entry Strict'


def _model_long_close_safe_alert_events(
    bar_confirmed: bool,
    long_setup_armed: bool,
    long_setup_confirmed: bool,
    long_ready_state: bool,
    long_setup_armed_prev: bool,
    long_setup_confirmed_prev: bool,
    long_ready_state_prev: bool,
) -> tuple[bool, bool, bool, bool]:
    long_arm_close_safe = bar_confirmed and long_setup_armed and not long_setup_armed_prev
    long_confirm_close_safe = bar_confirmed and long_setup_confirmed and not long_setup_confirmed_prev
    long_ready_close_safe = bar_confirmed and long_ready_state and not long_ready_state_prev
    long_invalidated_close_safe = bar_confirmed and not long_setup_armed and not long_setup_confirmed and (long_setup_armed_prev or long_setup_confirmed_prev)
    return long_arm_close_safe, long_confirm_close_safe, long_ready_close_safe, long_invalidated_close_safe


def _model_long_ready_alert_detail(
    long_setup_source_display: str,
    long_strict_alert_suffix: str,
    long_environment_alert_suffix: str,
    long_micro_alert_suffix: str,
    long_score_detail_suffix: str,
) -> str:
    return f'Ready for {long_setup_source_display}: lifecycle, gates, context, upgrades passed{long_strict_alert_suffix}{long_environment_alert_suffix}{long_micro_alert_suffix}{long_score_detail_suffix}'


def _model_long_confirmed_alert_detail(
    long_setup_source_display: str,
    long_strict_alert_suffix: str,
    long_environment_alert_suffix: str,
    long_micro_alert_suffix: str,
    long_score_detail_suffix: str,
) -> str:
    return f'Confirmed from {long_setup_source_display}: confirm lifecycle and filters passed{long_strict_alert_suffix}{long_environment_alert_suffix}{long_micro_alert_suffix}{long_score_detail_suffix}'


def _model_long_watchlist_alert_detail(
    long_micro_alert_suffix: str,
    long_score_detail_suffix: str,
) -> str:
    return f'Watchlist. Bullish trend plus active pullback zone{long_micro_alert_suffix}{long_score_detail_suffix}'


def _model_long_alert_identity(long_alert_kind: str) -> tuple[str, str]:
    seen_key = '|long_watchlist|'
    event_name = 'Long Dip Watchlist'
    if long_alert_kind == 'invalidated':
        seen_key = '|long_invalidated|'
        event_name = 'Long Invalidated'
    elif long_alert_kind == 'entry_strict':
        seen_key = '|long_entry_strict|'
        event_name = 'Long Dip Entry Strict'
    elif long_alert_kind == 'entry_best':
        seen_key = '|long_entry_best|'
        event_name = 'Long Dip Entry Best'
    elif long_alert_kind == 'ready':
        seen_key = '|long_ready|'
        event_name = 'Long Ready'
    elif long_alert_kind == 'confirmed':
        seen_key = '|long_confirmed|'
        event_name = 'Long Confirmed'
    elif long_alert_kind == 'clean':
        seen_key = '|long_clean|'
        event_name = 'Long Dip Clean'
    elif long_alert_kind == 'early':
        seen_key = '|long_early|'
        event_name = 'Long Dip Early'
    elif long_alert_kind == 'armed_plus':
        seen_key = '|long_armed_plus|'
        event_name = 'Long Dip Armed+'
    elif long_alert_kind == 'armed':
        seen_key = '|long_armed|'
        event_name = 'Long Armed'
    return seen_key, event_name


def _model_directional_dynamic_alert_identity(alert_kind: str, bullish: bool) -> tuple[str, str, str]:
    seen_key = '|bull_bos|' if bullish else '|bear_bos|'
    event_name = 'Bullish BOS' if bullish else 'Bearish BOS'
    detail = 'Structure break confirmed'
    if alert_kind == 'choch':
        seen_key = '|bull_choch|' if bullish else '|bear_choch|'
        event_name = 'Bullish CHoCH' if bullish else 'Bearish CHoCH'
        detail = 'Character shift confirmed'
    elif alert_kind == 'new_ob':
        seen_key = '|new_bull_ob|' if bullish else '|new_bear_ob|'
        event_name = 'Bullish Order Block' if bullish else 'Bearish Order Block'
        detail = 'New order block confirmed'
    elif alert_kind == 'new_fvg':
        seen_key = '|new_bull_fvg|' if bullish else '|new_bear_fvg|'
        event_name = 'Bullish FVG' if bullish else 'Bearish FVG'
        detail = 'New fair value gap formed'
    elif alert_kind == 'fvg_filled':
        seen_key = '|bull_fvg_filled|' if bullish else '|bear_fvg_filled|'
        event_name = 'Bullish FVG Filled' if bullish else 'Bearish FVG Filled'
        detail = 'Gap fill target reached'
    elif alert_kind == 'live_ob_break':
        seen_key = '|live_bull_ob_break|' if bullish else '|live_bear_ob_break|'
        event_name = 'Bullish OB Live Break' if bullish else 'Bearish OB Live Break'
        detail = 'Intrabar bullish order block break detected' if bullish else 'Intrabar bearish order block break detected'
    elif alert_kind == 'live_fvg_fill':
        seen_key = '|live_bull_fvg_fill|' if bullish else '|live_bear_fvg_fill|'
        event_name = 'Bullish FVG Live Fill' if bullish else 'Bearish FVG Live Fill'
        detail = 'Intrabar bullish fair value gap fill detected' if bullish else 'Intrabar bearish fair value gap fill detected'
    return seen_key, event_name, detail


def test_model_zone_candidate_priority_prefers_touch_anchor_then_recency_then_quality() -> None:
    assert _model_zone_candidate_preferred(True, 5, 0.2, 0.1, 10, False, 100, 0.9, 0.9, 99)
    assert _model_zone_candidate_preferred(False, 7, 0.2, 0.1, 10, False, 5, 0.9, 0.9, 99)
    assert _model_zone_candidate_preferred(False, 7, 0.8, 0.1, 10, False, 7, 0.2, 0.9, 99)
    assert _model_zone_candidate_preferred(False, 7, 0.8, 0.5, 10, False, 7, 0.8, 0.1, 99)
    assert _model_zone_candidate_preferred(False, 7, 0.8, 0.5, 11, False, 7, 0.8, 0.5, 10)


def test_model_long_invalidation_reason_uses_expected_precedence() -> None:
    assert _model_long_invalidation_reason(True, True, True, True, 'FVG', 'Swing Low', 'Swing Low -> FVG') == 'FVG source invalidated'
    assert _model_long_invalidation_reason(False, True, True, True, 'FVG', 'Swing Low', 'Swing Low -> FVG') == 'FVG backing zone lost'
    assert _model_long_invalidation_reason(False, False, True, True, 'FVG', 'Swing Low', 'Swing Low -> FVG') == 'Swing Low setup expired'
    assert _model_long_invalidation_reason(False, False, False, True, 'FVG', 'Swing Low', 'Swing Low -> FVG') == 'Swing Low confirm expired'
    assert _model_long_invalidation_reason(False, False, False, False, 'FVG', 'Swing Low', 'Swing Low -> FVG') == 'Swing Low -> FVG'


def test_model_long_setup_source_display_contract() -> None:
    assert _model_long_setup_source_display('None', 'OB') == 'OB'
    assert _model_long_setup_source_display('OB', 'OB') == 'OB'
    assert _model_long_setup_source_display('Swing Low', 'None') == 'Swing Low'
    assert _model_long_setup_source_display('Swing Low', 'FVG') == 'Swing Low -> FVG'


def test_model_long_ready_state_contract() -> None:
    ready, entry_best, entry_strict = _model_long_ready_states(
        True, True, True, True, True, True, True, True, True, True,
        True, True, True, True, True,
        True, True, True, True, True, True, True,
    )
    assert ready is True
    assert entry_best is True
    assert entry_strict is True

    ready, entry_best, entry_strict = _model_long_ready_states(
        False, True, True, True, True, True, True, True, True, True,
        True, True, True, True, True,
        True, True, True, True, True, True, True,
    )
    assert (ready, entry_best, entry_strict) == (False, False, False)

    ready, entry_best, entry_strict = _model_long_ready_states(
        True, True, True, True, True, True, True, True, True, True,
        True, True, True, True, True,
        False, True, True, True, True, True, True,
    )
    assert ready is True
    assert entry_best is True
    assert entry_strict is False


def test_model_long_setup_text_uses_latest_state_precedence() -> None:
    assert _model_long_setup_text(False, False, False, False, False, False, False, 'OB') == 'No Setup'
    assert _model_long_setup_text(True, False, False, False, False, False, False, 'OB') == 'In Zone'
    assert _model_long_setup_text(True, True, False, False, False, False, False, 'OB') == 'Armed | OB'
    assert _model_long_setup_text(True, True, True, True, True, True, True, 'OB') == 'Entry Strict | OB'


def test_model_long_visual_state_uses_latest_state_precedence_and_invalidation_override() -> None:
    assert _model_long_visual_state(False, False, False, False, False, False, False, False, False, False) == 0
    assert _model_long_visual_state(True, True, True, True, True, True, True, False, False, False) == 7
    assert _model_long_visual_state(True, True, True, True, True, True, True, True, False, True) == -1


def test_model_long_visual_text_contract() -> None:
    assert _model_long_visual_text(-1) == 'Blocked'
    assert _model_long_visual_text(0) == 'Neutral'
    assert _model_long_visual_text(5) == 'Long Ready'
    assert _model_long_visual_text(6) == 'Entry Best'
    assert _model_long_visual_text(7) == 'Entry Strict'


def test_model_long_close_safe_alert_events_only_fire_on_confirmed_transitions() -> None:
    assert _model_long_close_safe_alert_events(True, True, False, False, False, False, False) == (True, False, False, False)
    assert _model_long_close_safe_alert_events(True, False, True, True, False, False, False) == (False, True, True, False)
    assert _model_long_close_safe_alert_events(True, False, False, False, True, False, False) == (False, False, False, True)
    assert _model_long_close_safe_alert_events(False, True, True, True, False, False, False) == (False, False, False, False)


def test_model_long_alert_detail_contracts() -> None:
    ready_detail = _model_long_ready_alert_detail('Swing Low -> OB', ' | strict', ' | env', ' | micro', ' | score')
    confirmed_detail = _model_long_confirmed_alert_detail('OB', '', ' | env', ' | micro', ' | score')
    watchlist_detail = _model_long_watchlist_alert_detail(' | micro', ' | score')

    assert ready_detail == 'Ready for Swing Low -> OB: lifecycle, gates, context, upgrades passed | strict | env | micro | score'
    assert confirmed_detail == 'Confirmed from OB: confirm lifecycle and filters passed | env | micro | score'
    assert watchlist_detail == 'Watchlist. Bullish trend plus active pullback zone | micro | score'


def test_model_long_alert_identity_contract() -> None:
    assert _model_long_alert_identity('invalidated') == ('|long_invalidated|', 'Long Invalidated')
    assert _model_long_alert_identity('entry_best') == ('|long_entry_best|', 'Long Dip Entry Best')
    assert _model_long_alert_identity('armed') == ('|long_armed|', 'Long Armed')
    assert _model_long_alert_identity('watchlist') == ('|long_watchlist|', 'Long Dip Watchlist')


def test_model_directional_dynamic_alert_identity_contract() -> None:
    assert _model_directional_dynamic_alert_identity('bos', True) == ('|bull_bos|', 'Bullish BOS', 'Structure break confirmed')
    assert _model_directional_dynamic_alert_identity('choch', False) == ('|bear_choch|', 'Bearish CHoCH', 'Character shift confirmed')
    assert _model_directional_dynamic_alert_identity('new_ob', False) == ('|new_bear_ob|', 'Bearish Order Block', 'New order block confirmed')
    assert _model_directional_dynamic_alert_identity('live_fvg_fill', False) == ('|live_bear_fvg_fill|', 'Bearish FVG Live Fill', 'Intrabar bearish fair value gap fill detected')