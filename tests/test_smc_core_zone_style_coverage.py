from __future__ import annotations

from smc_core.layering import REGIME_STYLE


def test_regime_style_coverage() -> None:
    assert set(REGIME_STYLE.keys()) == {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}

    for style in REGIME_STYLE.values():
        assert 0.0 <= style.opacity <= 1.0
        assert style.line_width >= 1
