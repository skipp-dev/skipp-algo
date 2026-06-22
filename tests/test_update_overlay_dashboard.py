"""Unit tests for scripts/update_overlay_dashboard.py.

Covers idempotent dashboard UX transformations.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def temp_dashboard(tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dst = tmp_path / "dashboard.json"
    shutil.copy(src, dst)
    return dst


def _run_script(dashboard_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "update_overlay_dashboard.py"
    env = {"PYTHONPATH": str(repo_root)}
    result = subprocess.run(
        [sys.executable, str(script), str(dashboard_path)],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_update_script_adds_uptimerobot_state_timeline(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dst = tmp_path / "dashboard.json"
    shutil.copy(src, dst)

    original = json.loads(dst.read_text(encoding="utf-8"))
    titles_before = {p["title"] for p in original["panels"]}
    assert "UptimeRobot Monitor States" in titles_before

    # Remove the panel to test re-creation.
    original["panels"] = [p for p in original["panels"] if p["title"] != "UptimeRobot Monitor States"]
    dst.write_text(json.dumps(original, indent=2), encoding="utf-8")

    _run_script(dst)

    updated = json.loads(dst.read_text(encoding="utf-8"))
    titles_after = {p["title"] for p in updated["panels"]}
    assert "UptimeRobot Monitor States" in titles_after
    panel = next(p for p in updated["panels"] if p["title"] == "UptimeRobot Monitor States")
    assert panel["type"] == "state-timeline"


def test_update_script_preserves_existing_panels(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dst = tmp_path / "dashboard.json"
    shutil.copy(src, dst)

    original_titles = {p["title"] for p in json.loads(src.read_text(encoding="utf-8"))["panels"]}
    _run_script(dst)
    updated_titles = {p["title"] for p in json.loads(dst.read_text(encoding="utf-8"))["panels"]}
    assert "News Provider State Codes" in updated_titles
    assert "Stale Budget Consumed (%)" in updated_titles
    assert original_titles.issubset(updated_titles)


def test_no_duplicate_fallback_queries_after_update(temp_dashboard: Path) -> None:
    """Newer Grafana renders each branch of `or` separately; avoid duplicates."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    for panel in data["panels"]:
        exprs = [t.get("expr", "") for t in panel.get("targets", [])]
        for expr in exprs:
            if " or " not in expr:
                continue
            first = expr.split(" or ")[0].strip()
            bare_first = first.split("{")[0] if "{" in first else first
            rest = [part.strip() for part in expr.split(" or ")[1:] if not part.strip().startswith("vector(")]
            for part in rest:
                bare_part = part.split("{")[0] if "{" in part else part
                assert bare_part != bare_first, f"Panel {panel['title']!r} has duplicate fallback: {expr[:200]}"


def test_latency_panels_consolidated_and_slo_added(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    titles = {p["title"] for p in data["panels"]}
    assert "smc_live Latency Avg (ms)" not in titles
    assert "smc_live Latency Buckets (req/s)" not in titles
    assert "Latency vs. SLO (ms)" in titles
    panel = next(p for p in data["panels"] if p["title"] == "Latency vs. SLO (ms)")
    exprs = [t.get("expr", "") for t in panel["targets"]]
    assert any("vector(500)" in e for e in exprs)


def test_news_state_code_panel_has_value_mapping(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p["title"] == "News Providers — State Code")
    options = panel["fieldConfig"]["defaults"]["mappings"][0].get("options", {})
    assert options.get("0", {}).get("text") == "UNKNOWN"
    assert options.get("1", {}).get("text") == "DEGRADED"
    assert options.get("2", {}).get("text") == "OK"


def test_overall_health_ampel_and_oncall_row_present(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    titles = {p["title"] for p in data["panels"]}
    assert "Overall Health" in titles
    assert "Incident Triage Guide" in titles
    assert {
        "Feed Healthy",
        "Overlay Fresh",
        "Workers Healthy",
        "Bridge Scrapes",
        "Market Status",
        "Last Bar Age",
    }.issubset(titles)


def test_deploy_restart_annotations_present(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    names = {a.get("name") for a in data.get("annotations", {}).get("list", [])}
    assert "Deploys / Restarts" in names
