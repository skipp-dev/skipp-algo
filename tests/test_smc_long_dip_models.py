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