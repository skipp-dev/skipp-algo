"""Contract pins for the Signals & Experiments dashboard redesign (2026-07-08).

Same standing spec as the main dashboard: user-first sections, all expanded,
calm palette, state readable by label, a slim cross-link banner on top. Plus
the operator decision to drop the UptimeRobot ops panel here (it lives on the
main operations dashboard).
"""
from __future__ import annotations

import json
from pathlib import Path

_DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "services" / "live_overlay_daemon" / "infra" / "grafana"
    / "dashboard-signals-experiments.json"
)

SECTION_ORDER = ["Live Trading Signals", "Daily Experiment (Phase E2)"]


def _load() -> dict:
    return json.loads(_DASHBOARD.read_text(encoding="utf-8"))


def _rows(d: dict) -> list[dict]:
    return [p for p in sorted(d["panels"], key=lambda p: p["gridPos"]["y"]) if p.get("type") == "row"]


def _visual_panels(d: dict) -> list[dict]:
    return [p for p in d["panels"] if p.get("type") != "row"]


def test_sections_are_user_first_and_all_expanded() -> None:
    d = _load()
    rows = _rows(d)
    assert [r["title"] for r in rows] == SECTION_ORDER
    for r in rows:
        assert r.get("collapsed") is False, r["title"]
        assert r.get("description"), r["title"]


def test_top_cross_link_banner_present() -> None:
    d = _load()
    banner = next((p for p in _visual_panels(d) if p.get("id") == 999), None)
    assert banner is not None and banner["type"] == "text"
    assert banner["gridPos"]["y"] == 0
    content = banner["options"]["content"]
    assert "/d/smc-live-overlay-v1" in content
    assert _rows(d)[0]["gridPos"]["y"] >= banner["gridPos"]["h"]


def test_uptimerobot_ops_panel_removed() -> None:
    """UptimeRobot uptime monitoring belongs on the main operations dashboard."""
    d = _load()
    titles = {p.get("title") for p in _visual_panels(d)}
    assert "UptimeRobot Monitor States" not in titles


def test_no_grid_overlaps() -> None:
    d = _load()
    panels = _visual_panels(d)
    for i, a in enumerate(panels):
        ag = a["gridPos"]
        for b in panels[i + 1:]:
            bg = b["gridPos"]
            overlap = (
                ag["x"] < bg["x"] + bg["w"] and bg["x"] < ag["x"] + ag["w"]
                and ag["y"] < bg["y"] + bg["h"] and bg["y"] < ag["y"] + ag["h"]
            )
            assert not overlap, f"{a.get('title')} overlaps {b.get('title')}"


def test_all_panels_have_descriptions() -> None:
    d = _load()
    missing = [p.get("title") for p in _visual_panels(d) if not p.get("description")]
    assert not missing, f"panels missing description: {missing}"


def test_every_signal_panel_is_in_a_section() -> None:
    """No panel floats above the first section (except the banner at y=0)."""
    d = _load()
    first_row_y = _rows(d)[0]["gridPos"]["y"]
    for p in _visual_panels(d):
        if p.get("id") == 999:
            continue
        assert p["gridPos"]["y"] >= first_row_y, p.get("title")
