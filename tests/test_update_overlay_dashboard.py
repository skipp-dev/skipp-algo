"""Unit tests for scripts/update_overlay_dashboard.py.

Covers idempotent dashboard UX transformations.
"""

from __future__ import annotations

import json
import os
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
        env={**os.environ, **env},
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
    # Per-monitor status-code metrics are named live_overlay_uptimerobot_monitor_<id>_status_code
    assert "live_overlay_uptimerobot_monitor_.*_status_code" in panel["targets"][0]["expr"]
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options["0"]["text"] == "PAUSED"
    assert options["1"]["text"] == "NOT CHECKED"
    assert options["2"]["text"] == "UP"
    assert options["8"]["text"] == "DOWN"
    assert options["9"]["text"] == "DOWN"


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


def test_update_script_is_idempotent(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    first = temp_dashboard.read_text(encoding="utf-8")
    _run_script(temp_dashboard)
    second = temp_dashboard.read_text(encoding="utf-8")
    assert first == second, "Re-running the updater changed dashboard.json"


def test_all_panel_queries_have_balanced_parentheses(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    for panel in data["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if not expr:
                continue
            assert expr.count("(") == expr.count(")"), f"Unbalanced parentheses in {panel['title']!r}: {expr[:200]}"


def test_update_script_fixes_bridge_scrapes_query(temp_dashboard: Path) -> None:
    """Bridge Scrapes should ignore unconfigured bridges, not treat them as failures."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "Bridge Scrapes")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_uptimerobot_scrape_success" in expr
    assert "live_overlay_github_workflow_scrape_success" in expr
    assert expr.endswith(") or vector(0)")


def test_update_script_fixes_bridge_error_panels(temp_dashboard: Path) -> None:
    """Bridge error panels must not count the healthy error_code="none" series."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    for title in ("UptimeRobot Bridge Error", "GitHub Workflow Bridge Error"):
        panel = next(p for p in data["panels"] if p.get("title") == title)
        expr = panel["targets"][0]["expr"]
        assert 'error_code!="none"' in expr, f"{title}: {expr[:200]}"


def test_update_script_adds_railway_status_panels(temp_dashboard: Path) -> None:
    """Railway row should expose bridge status, snapshot age, and error class."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in data["panels"]}
    assert "Railway Metrics Bridge" in titles
    assert "Railway Metrics Snapshot Age" in titles
    assert "Railway Metrics Error" in titles

    bridge = next(p for p in data["panels"] if p.get("title") == "Railway Metrics Bridge")
    assert "live_overlay_railway_metrics_enabled" in bridge["targets"][0]["expr"]


def test_update_script_fixes_github_workflow_timeline_readability(temp_dashboard: Path) -> None:
    """The GitHub Workflow Status timeline must be tall enough and colour-coded."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "GitHub Workflow Status — Timeline")
    assert panel["type"] == "state-timeline"
    assert panel["gridPos"]["h"] >= 25
    assert "gray=unknown, purple=skipped" in panel["description"]
    assert panel["options"]["showValue"] == "auto"
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["color"]["mode"] == "thresholds"
    steps = defaults["thresholds"]["steps"]
    codes = {step["value"] for step in steps}
    assert codes >= {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
    mapping_codes = set()
    for mapping in defaults["mappings"]:
        mapping_codes.update(mapping.get("options", {}).keys())
    assert mapping_codes >= {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"}
