from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = ROOT / "open_prep_boundary.py"
WORKFLOW_PATH = ROOT / ".github/workflows/smc-deeper-integration-gates.yml"
RT_PROMOTION_PATH = ROOT / "open_prep/rt_promotion.py"

FMP_BOUNDARY_CONSUMERS = [
    "databento_universe.py",
    "databento_volatility_screener.py",
    "scripts/databento_production_export.py",
    "smc_tv_bridge/adapters_open_prep.py",
    "terminal_bitcoin.py",
    "terminal_fmp_insights.py",
    "terminal_fmp_technicals.py",
    "terminal_forecast.py",
    "terminal_poller.py",
    "terminal_spike_scanner.py",
    "terminal_tabs/tab_fmp_ai.py",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deeper_integration_workflow_uses_release_policy_defaults() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert "--symbols" not in workflow_text
    assert "--stale-after-seconds" not in workflow_text


def test_rt_promotion_helper_is_lightweight_and_shared() -> None:
    helper_text = _read(RT_PROMOTION_PATH)
    streamlit_text = _read(ROOT / "open_prep/streamlit_monitor.py")
    test_text = _read(ROOT / "tests/test_rt_promotion.py")

    assert "import streamlit" not in helper_text
    assert "from open_prep.rt_promotion import promote_a0a1_signals" in streamlit_text
    assert "from open_prep.rt_promotion import promote_a0a1_signals" in test_text


def test_open_prep_fmp_runtime_boundary_is_centralized() -> None:
    boundary_text = _read(BOUNDARY_PATH)

    assert "from open_prep.macro import FMPClient" in boundary_text
    for relative_path in FMP_BOUNDARY_CONSUMERS:
        source = _read(ROOT / relative_path)
        assert "from open_prep.macro import FMPClient" not in source


def test_bridge_runtime_imports_are_routed_through_boundary() -> None:
    source = _read(ROOT / "smc_tv_bridge/adapters_open_prep.py")

    assert "from open_prep.realtime_signals import VolumeRegimeDetector" not in source
    assert "from open_prep.realtime_signals import TechnicalScorer" not in source
