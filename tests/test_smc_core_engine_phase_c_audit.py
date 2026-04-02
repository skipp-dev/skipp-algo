from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "SMC_Core_Engine.pine"
REMOVED_PHASE_C_C1_INPUTS = [
    "show_mtf_trend",
    "show_risk_levels",
    "show_reclaim_markers",
    "show_long_confirmation_markers",
    "show_long_background",
    "color_long_bars",
    "show_accel_debug",
    "show_sd_debug",
    "show_vol_regime_debug",
    "show_stretch_overlay",
    "show_lower_extreme_bg",
]


def _read_engine_source() -> str:
    return ENGINE_PATH.read_text(encoding="utf-8")


def test_phase_c_c1_removed_inputs_stay_absent() -> None:
    source = _read_engine_source()

    for name in REMOVED_PHASE_C_C1_INPUTS:
        assert re.search(rf"\b{name}\b", source) is None, f"{name} reappeared after the Phase C C1 removal batch"