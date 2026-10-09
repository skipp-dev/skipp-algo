"""Tests for Amendment A1.C — Pine codegen for tri-axis FVG health."""

from __future__ import annotations

from smc_core.benchmark import stratified_fvg_report
from smc_core.fvg_pine_emit import (
    PINE_PREFIX,
    emit_fvg_pine_block,
    emit_fvg_pine_constants,
)


def _evt(session: str, vol: str, htf: str, hit: bool) -> dict:
    return {"session": session, "vol_regime": vol, "htf_bias": htf, "hit": hit}


def _strong_corpus() -> list[dict]:
    # 16 NY_AM/NORMAL events with 75% HR (passes 0.70), 16 ASIA/HIGH_VOL with 50%.
    events = []
    for i in range(16):
        events.append(_evt("NY_AM", "NORMAL", "BULL", i < 12))
    for i in range(16):
        events.append(_evt("ASIA", "HIGH_VOL", "BEAR", i < 8))
    # 4-event insufficient bucket
    for i in range(4):
        events.append(_evt("LONDON", "LOW_VOL", "BULL", i < 2))
    return events


def test_emits_one_pair_per_cell() -> None:
    report = stratified_fvg_report(_strong_corpus())
    lines = emit_fvg_pine_constants(report)
    # Header + 2 lines per cell × 3 cells = 7
    assert lines[0].startswith("// ── FVG Tri-Axis Health")
    decls = [ln for ln in lines if ln.startswith("export const")]
    assert len(decls) == 6  # 3 cells × (value + status)


def test_pine_constants_deterministic() -> None:
    report = stratified_fvg_report(_strong_corpus())
    a = emit_fvg_pine_block(report)
    b = emit_fvg_pine_block(report)
    assert a == b


def test_status_classification() -> None:
    report = stratified_fvg_report(_strong_corpus())
    block = emit_fvg_pine_block(report)
    # NY_AM/NORMAL @ 75% HR -> OK
    assert f'{PINE_PREFIX}_NY_AM_NORMAL_STATUS = "OK"' in block
    # ASIA/HIGH_VOL @ 50% HR -> WEAK
    assert f'{PINE_PREFIX}_ASIA_HIGH_VOL_STATUS = "WEAK"' in block
    # LONDON/LOW_VOL n=4 < min_events -> INSUF
    assert f'{PINE_PREFIX}_LONDON_LOW_VOL_STATUS = "INSUF"' in block


def test_insufficient_bucket_rendered_as_string() -> None:
    report = stratified_fvg_report(_strong_corpus())
    block = emit_fvg_pine_block(report)
    # 4 events / 12 min -> insufficient
    assert f'{PINE_PREFIX}_LONDON_LOW_VOL = "insufficient (n=4)"' in block


def test_empty_report_produces_only_header() -> None:
    report = stratified_fvg_report([])
    lines = emit_fvg_pine_constants(report)
    assert len(lines) == 1
    assert lines[0].startswith("// ──")


def test_safe_identifier_no_special_chars() -> None:
    events = [_evt("NY-AM!", "HIGH VOL", "BULL", True) for _ in range(16)]
    events.extend(_evt("NY-AM!", "HIGH VOL", "BULL", False) for _ in range(16))
    report = stratified_fvg_report(events)
    block = emit_fvg_pine_block(report)
    # The safe-token strips '-' and '!' and ' '.
    assert f"{PINE_PREFIX}_NYAM_HIGHVOL " in block


def test_constant_format_matches_pine_v5() -> None:
    report = stratified_fvg_report(_strong_corpus())
    for line in emit_fvg_pine_constants(report):
        if line.startswith("export const"):
            # All declarations must be exactly:
            # "export const string IDENT = \"...\""
            assert " string " in line
            assert " = \"" in line
            assert line.endswith('"')


def test_value_string_contains_hr_and_n() -> None:
    report = stratified_fvg_report(_strong_corpus())
    block = emit_fvg_pine_block(report)
    # NY_AM NORMAL: 12 hits / 16 = 75%
    assert f'{PINE_PREFIX}_NY_AM_NORMAL = "75% (n=16)"' in block
