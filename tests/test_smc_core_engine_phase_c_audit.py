from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "SMC_Core_Engine.pine"
PHASE_C_DEAD_INPUT_CANDIDATES = [
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


def test_phase_c_dead_input_candidates_are_still_declaration_only() -> None:
    source = _read_engine_source()

    for name in PHASE_C_DEAD_INPUT_CANDIDATES:
        matches = re.findall(rf"\b{name}\b", source)
        assert len(matches) == 1, f"{name} is no longer declaration-only and must be re-audited before Phase C removal"