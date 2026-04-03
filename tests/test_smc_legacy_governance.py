from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "docs/smc_deep_research_migration_plan_copilot.md"
PHASE_C_PATH = ROOT / "docs/PHASE_C_ANALYSIS.md"
RELEASE_DOC_PATH = ROOT / "docs/smc_branch_protection_and_release_gates.md"
WORKFLOW_PATH = ROOT / ".github/workflows/smc-release-gates.yml"
CORE_PATH = ROOT / "SMC_Core_Engine.pine"
LONG_DIP_REGRESSION_PATH = ROOT / "tests/test_smc_long_dip_regressions.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_smc_plus_freeze_policy_is_explicit_in_docs() -> None:
    plan_text = _read(PLAN_PATH)
    phase_c_text = _read(PHASE_C_PATH)

    assert "`SMC++.pine` ist ab jetzt der eingefrorene Kompatibilitaetspfad." in plan_text
    assert "`SMC++.pine` is the frozen compatibility path." in phase_c_text


def test_release_policy_targets_split_core_and_keeps_legacy_anchor() -> None:
    release_doc_text = _read(RELEASE_DOC_PATH)

    assert "`SMC_Core_Engine.pine` ist der release-verbindliche Producer" in release_doc_text
    assert "`SMC++.pine` bleibt eingefrorener Kompatibilitaetspfad." in release_doc_text


def test_release_gate_matrix_keeps_frozen_compatibility_checks() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "tests/test_smc_long_dip_regressions.py" in workflow_text
    assert "tests/test_smc_legacy_governance.py" in workflow_text


def test_long_dip_regression_stays_anchored_to_smc_plus() -> None:
    regression_text = _read(LONG_DIP_REGRESSION_PATH)

    assert "SMC_PATH = ROOT / 'SMC++.pine'" in regression_text


def test_long_dip_first_scope_is_documented_in_active_core_and_plan() -> None:
    core_text = _read(CORE_PATH)
    plan_text = _read(PLAN_PATH)

    assert "Long-Dip-first" in plan_text
    assert "Product scope: this script is the active long-dip specialist surface." in core_text