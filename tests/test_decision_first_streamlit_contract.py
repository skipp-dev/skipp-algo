"""Tripwires for the Streamlit Decision-First wiring contract."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_streamlit_tab_uses_shared_loader_and_default_path() -> None:
    source = _read("streamlit_terminal.py")
    assert "load_decisions_from_report" in source
    assert "DEFAULT_PROMOTION_DECISIONS_PATH" in source
    assert "render_decision_first_panel" in source
    assert "promotion_decisions" in source
    assert "promotion_walkforward_histories" in source
    # EV-09 (2026-08-18, Verdrahtungs-Sweep E2): der Verdict-Aufsatz hatte
    # null Produktions-Importer, während dieser Test den ALTEN Pfad allein
    # festpinnte — jetzt pinnen beide Panels gemeinsam.
    assert "render_panel_from_archive" in source


def test_streamlit_tab_advertises_runner_output_contract() -> None:
    source = _read("streamlit_terminal.py")
    assert "scripts/run_promotion_gate.py" in source
    assert "No promotion decisions available yet." in source
