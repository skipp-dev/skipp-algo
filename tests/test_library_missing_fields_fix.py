"""WP-OH9: Verify all previously-missing Pine-consumed library fields are now exported."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "generate_smc_micro_profiles.py"

# Fields that were missing before WP-OH9 (Pine reads mp.FIELD but no export const existed).
# NOTE: OB Extended fields (9) removed in WP-8 sunset — zero Pine consumers remain.
WP_OH9_FIELDS = {
    # Imbalance lifecycle
    "BPR_DIRECTION",
    # Liquidity pools
    "BUY_SIDE_POOL_LEVEL",
    "BUY_SIDE_POOL_STRENGTH",
    # Event risk
    "HIGH_RISK_EVENT_TICKERS",
    "NEXT_EVENT_CLASS",
    # Liquidity sweeps
    "LIQUIDITY_TAKEN_DIRECTION",
}


def _extract_generator_fields() -> set[str]:
    source = GENERATOR.read_text(encoding="utf-8")
    fields: set[str] = set()
    fields.update(re.findall(r"export const (?:float|int|bool|string) ([A-Z_][A-Z0-9_]+)", source))
    fields.update(re.findall(r'render_csv_export\(\s*"([A-Z_][A-Z0-9_]+)"', source))
    return fields


class TestAllConsumedFieldsExported:
    def test_all_wp_oh9_fields_present_in_generator(self) -> None:
        generated = _extract_generator_fields()
        missing = WP_OH9_FIELDS - generated
        assert missing == set(), f"Still missing from generator: {sorted(missing)}"


class TestMacroBiasExported:
    def test_macro_bias_in_generator(self) -> None:
        generated = _extract_generator_fields()
        assert "MACRO_BIAS" in generated, "MACRO_BIAS must be exported"

    def test_macro_bias_reads_from_regime_enrichment(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        assert 'regime.get("macro_bias"' in source, (
            "MACRO_BIAS must read from regime enrichment dict"
        )


class TestFieldDefaults:
    """Verify each WP-OH9 field uses a known DEFAULTS dict for its fallback."""

    def test_ob_fields_removed_in_wp8(self) -> None:
        """OB Extended fields removed in WP-8 sunset; _OB_DEFAULTS no longer needed."""
        source = GENERATOR.read_text(encoding="utf-8")
        assert "_OB_DEFAULTS" not in source

    def test_imbalance_field_uses_il_defaults(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        assert "_IL_DEFAULTS" in source

    def test_liquidity_pools_uses_lp_defaults(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        assert "_LP_DEFAULTS" in source

    def test_liquidity_sweeps_uses_ls_defaults(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        assert "_LS_DEFAULTS" in source

    def test_event_risk_high_risk_tickers_uses_er_defaults(self) -> None:
        source = GENERATOR.read_text(encoding="utf-8")
        assert 'HIGH_RISK_EVENT_TICKERS' in source
        assert '_ER_DEFAULTS' in source
