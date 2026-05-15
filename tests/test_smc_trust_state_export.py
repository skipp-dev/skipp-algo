"""Tests for the Trust-State export glue (ENG-WS2-02)."""
from __future__ import annotations

from pathlib import Path

from scripts.smc_trust_state_export import (
    PINE_TRUST_FIELDS,
    attach_trust_state_to_enrichment,
    render_trust_block_lines,
    trust_block_for_export,
)

# ── attach_trust_state_to_enrichment ──────────────────────────────────


class TestAttach:
    def test_attach_to_none_enrichment_is_noop(self) -> None:
        assert attach_trust_state_to_enrichment(None, {"overall_status": "ok"}) is None

    def test_attach_with_no_provider_report_is_noop(self) -> None:
        enr: dict = {}
        out = attach_trust_state_to_enrichment(enr, None)
        assert out is enr
        assert "trust_state" not in enr

    def test_attach_writes_full_assessment_dict(self) -> None:
        enr: dict = {}
        attach_trust_state_to_enrichment(
            enr,
            {
                "overall_status": "fail",
                "domain_alerts": [
                    {"domain": "structure", "code": "MISSING_STRUCTURE_DOMAIN"}
                ],
            },
        )
        block = enr["trust_state"]
        assert block["state"] == "unavailable"
        assert block["action_impact"] == "suppress_product"
        assert block["cause"]["domain"] == "structure"
        # JSON-friendly: every key is a plain Python type.
        assert isinstance(block["contributing_alerts"], list)


# ── trust_block_for_export ────────────────────────────────────────────


class TestExportBlock:
    def test_uses_trust_state_when_present(self) -> None:
        enr = {
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure",
                    "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Structure stale > 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            }
        }
        block = trust_block_for_export(enr)
        assert block["state"] == "watch_only"
        assert block["cause"]["code"] == "STALE_MANIFEST_GENERATED_AT"

    def test_falls_back_to_healthy_when_absent(self) -> None:
        block = trust_block_for_export({"providers": {"provider_count": 3}})
        assert block["state"] == "healthy"
        assert block["action_impact"] == "none"
        assert block["cause"]["domain"] is None

    def test_falls_back_to_stale_when_legacy_stale_providers_set(self) -> None:
        block = trust_block_for_export({"providers": {"stale_providers": "fmp_candles"}})
        assert block["state"] == "stale"
        assert block["action_impact"] == "advisory_only"
        assert block["cause"]["code"] == "STALE_PROVIDERS"
        assert "fmp_candles" in (block["cause"]["description"] or "")

    def test_returned_block_is_independent_copy(self) -> None:
        enr = {
            "trust_state": {
                "state": "degraded",
                "action_impact": "advisory_only",
                "cause": {
                    "domain": "news",
                    "failure_type": "fallback",
                    "code": "NEWS_FALLBACK",
                    "description": "Benzinga fallback",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "warn",
            }
        }
        block = trust_block_for_export(enr)
        block["state"] = "TAMPERED"
        block["cause"]["code"] = "TAMPERED"
        # Original must remain intact.
        assert enr["trust_state"]["state"] == "degraded"
        assert enr["trust_state"]["cause"]["code"] == "NEWS_FALLBACK"


# ── render_trust_block_lines ──────────────────────────────────────────


def _trust_lines_to_dict(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        if not line.startswith("export const"):
            continue
        # Format: ``export const <type> <NAME> = <value>``
        head, _, value = line.partition("=")
        name = head.strip().split()[-1]
        out[name] = value.strip().strip('"')
    return out


class TestRender:
    def test_emits_all_six_fields_in_stable_order(self) -> None:
        lines = render_trust_block_lines({})
        # Header + 6 fields.
        assert lines[0] == "// ── Trust State (ENG-WS2-02) ──"
        names = [
            line.split()[3] for line in lines if line.startswith("export const")
        ]
        assert names == list(PINE_TRUST_FIELDS)

    def test_healthy_default_for_empty_enrichment(self) -> None:
        rendered = _trust_lines_to_dict(render_trust_block_lines({}))
        assert rendered["TRUST_STATE"] == "healthy"
        assert rendered["TRUST_ACTION_IMPACT"] == "none"
        assert rendered["TRUST_CAUSE_DOMAIN"] == ""
        assert rendered["TRUST_CAUSE_FAILURE_TYPE"] == ""
        assert rendered["TRUST_CAUSE_CODE"] == ""
        assert rendered["TRUST_DEGRADATION_REASON"] == ""

    def test_renders_full_cause_when_trust_state_is_set(self) -> None:
        enr = {
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure",
                    "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Structure stale > 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            }
        }
        rendered = _trust_lines_to_dict(render_trust_block_lines(enr))
        assert rendered["TRUST_STATE"] == "watch_only"
        assert rendered["TRUST_ACTION_IMPACT"] == "no_new_entries"
        assert rendered["TRUST_CAUSE_DOMAIN"] == "structure"
        assert rendered["TRUST_CAUSE_FAILURE_TYPE"] == "stale"
        assert rendered["TRUST_CAUSE_CODE"] == "STALE_MANIFEST_GENERATED_AT"
        assert rendered["TRUST_DEGRADATION_REASON"] == "Structure stale > 24h"

    def test_pine_strings_escape_quotes_and_backslashes(self) -> None:
        enr = {
            "trust_state": {
                "state": "stale",
                "action_impact": "advisory_only",
                "cause": {
                    "domain": "providers",
                    "failure_type": "stale",
                    "code": "X",
                    "description": 'Reason with "quotes" and \\backslash',
                },
                "contributing_alerts": [],
                "derived_from_overall_status": None,
            }
        }
        lines = render_trust_block_lines(enr)
        # Find the degradation_reason line and assert it remains valid Pine.
        reason_line = next(ln for ln in lines if "TRUST_DEGRADATION_REASON" in ln)
        assert reason_line.endswith('"')
        # Backslash and quote must both be escaped.
        assert '\\\\backslash' in reason_line
        assert '\\"quotes\\"' in reason_line


# ── End-to-end: write_pine_library actually emits the block ───────────


class TestPineLibraryEmission:
    def test_pine_library_emits_trust_block_with_healthy_default(
        self, tmp_path: Path
    ) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment={"providers": {"provider_count": 0, "stale_providers": ""}},
        )
        text = out.read_text(encoding="utf-8")
        assert "// ── Trust State (ENG-WS2-02) ──" in text
        assert 'export const string TRUST_STATE = "healthy"' in text
        assert 'export const string TRUST_ACTION_IMPACT = "none"' in text
        assert 'export const string TRUST_CAUSE_DOMAIN = ""' in text

    def test_pine_library_emits_full_trust_block_when_set(
        self, tmp_path: Path
    ) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        enrichment = {
            "providers": {"provider_count": 3, "stale_providers": "fmp_candles"},
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure",
                    "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Structure artifact older than 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            },
        }
        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment=enrichment,
        )
        text = out.read_text(encoding="utf-8")
        assert 'export const string TRUST_STATE = "watch_only"' in text
        assert 'export const string TRUST_ACTION_IMPACT = "no_new_entries"' in text
        assert 'export const string TRUST_CAUSE_CODE = "STALE_MANIFEST_GENERATED_AT"' in text
        assert (
            'export const string TRUST_DEGRADATION_REASON = "Structure artifact older than 24h"'
            in text
        )
        # Legacy provider fields remain unchanged.
        assert "export const int PROVIDER_COUNT = 3" in text
        assert 'export const string STALE_PROVIDERS = "fmp_candles"' in text

    def test_pine_library_synthesises_stale_block_from_legacy_providers(
        self, tmp_path: Path
    ) -> None:
        """When the upstream pipeline only sets ``providers.stale_providers``
        (no trust_state block yet), the export must still surface STALE so
        the Pine consumer doesn't read HEALTHY for a degraded snapshot."""
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment={
                "providers": {"provider_count": 2, "stale_providers": "newsapi"},
            },
        )
        text = out.read_text()
        assert 'export const string TRUST_STATE = "stale"' in text
        assert 'export const string TRUST_ACTION_IMPACT = "advisory_only"' in text
        assert 'export const string TRUST_CAUSE_CODE = "STALE_PROVIDERS"' in text
        assert "newsapi" in text
