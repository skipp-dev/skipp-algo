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

SECTION_ORDER = [
    "Live Trading Signals",
    "Daily Experiment (Phase E2)",
    "Sweep-Trap Shadow (WS4a)",
]


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


def test_sweep_trap_shadow_panels_query_the_ws4a_gauges() -> None:
    """The WS4a section surfaces the verdict, Brier-delta, lift, sample accrual
    and snapshot age from the sweep_trap_shadow gauges."""
    d = _load()
    exprs = " ".join(
        t.get("expr", "")
        for p in _visual_panels(d)
        for t in p.get("targets", [])
    )
    for metric in (
        "live_overlay_sweep_trap_shadow_verdict_code",
        "live_overlay_sweep_trap_shadow_brier_delta",
        "live_overlay_sweep_trap_shadow_lift",
        "live_overlay_sweep_trap_shadow_sample_count",
        "live_overlay_sweep_trap_shadow_snapshot_age_seconds",
        "live_overlay_sweep_trap_shadow_evidence_info",
    ):
        assert metric in exprs, f"no panel queries {metric}"


def test_sweep_trap_latest_evidence_table_has_date_value_and_assessment() -> None:
    d = _load()
    panel = next(
        (p for p in _visual_panels(d) if p.get("title") == "Sweep-Trap Evidence — Latest"),
        None,
    )
    assert panel is not None
    assert panel["type"] == "table"
    assert panel["targets"][0]["expr"] == 'live_overlay_sweep_trap_shadow_evidence_info{job=~"$job"}'
    organize = next(t for t in panel["transformations"] if t["id"] == "organize")
    assert organize["options"]["renameByName"] == {
        "date": "Datum",
        "metric": "Kennzahl",
        "value": "Wert",
        "assessment": "Bewertung",
    }


def test_sweep_trap_shadow_verdict_panel_maps_all_three_codes() -> None:
    """The verdict tile must decode 0/1/2 to human labels, not raw codes."""
    d = _load()
    verdict = next(
        (p for p in _visual_panels(d) if p.get("title") == "Sweep-Trap Shadow Verdict"),
        None,
    )
    assert verdict is not None
    mappings = verdict["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert mappings["0"]["text"] == "INCONCLUSIVE"
    assert mappings["1"]["text"] == "SHADOW"
    assert mappings["2"]["text"] == "PROMOTABLE"
