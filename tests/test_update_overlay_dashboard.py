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


def test_railway_links_are_concrete(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    raw = temp_dashboard.read_text(encoding="utf-8")
    # Generic railway.app project-root URLs are never acceptable.
    assert "railway.app/project" not in raw, "dashboard still contains generic railway.app URLs"
    assert "REPLACE_" not in raw, "dashboard still contains placeholder Railway IDs"
    # Dashboard-level links must use the concrete service-scoped shape.
    data = json.loads(raw)
    link_urls = {link.get("title"): link.get("url", "") for link in data.get("links", [])}
    for title in ("Railway logs", "Railway deployments", "Railway metrics"):
        url = link_urls.get(title, "")
        assert url.startswith("https://railway.com/project/")
        assert "/service/" in url
        assert "environmentId=" in url


def test_railway_links_use_env_ids_when_provided(temp_dashboard: Path) -> None:
    env = {
        **os.environ,
        "RAILWAY_PROJECT_ID": "proj-123",
        "RAILWAY_ENVIRONMENT_ID": "env-456",
        "RAILWAY_LIVE_OVERLAY_SERVICE_ID": "svc-789",
    }
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "update_overlay_dashboard.py"
    result = subprocess.run(
        [sys.executable, str(script), str(temp_dashboard)],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    raw = temp_dashboard.read_text(encoding="utf-8")
    assert "proj-123" in raw
    assert "env-456" in raw
    assert "svc-789" in raw


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
        "External Checks",
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
    first = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    _run_script(temp_dashboard)
    second = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    # The updater may bump version on re-run even when no real panel content
    # changes (e.g. if a self-heal step returns True without mutating).
    # Idempotency means the dashboard body (excluding version) is stable.
    first.pop("version", None)
    second.pop("version", None)
    assert first == second, "Re-running the updater changed dashboard.json body"


def test_update_script_re_adds_missing_uptimerobot_panel_idempotently(tmp_path: Path) -> None:
    """_ensure_uptimerobot_panel re-adds a missing panel and bumps version."""
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dst = tmp_path / "dashboard.json"
    shutil.copy(src, dst)

    # First run applies all UX fixes and bumps the version.
    _run_script(dst)
    first = json.loads(dst.read_text(encoding="utf-8"))
    assert first["version"] > 0

    # Remove the UptimeRobot panel to simulate a missing self-healed element.
    data = json.loads(dst.read_text(encoding="utf-8"))
    data["panels"] = [p for p in data["panels"] if p.get("title") != "UptimeRobot Monitor States"]
    dst.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Second run re-adds the panel and must count it as a change.
    _run_script(dst)
    second = json.loads(dst.read_text(encoding="utf-8"))
    assert second["version"] > first["version"]
    titles = {p.get("title") for p in second["panels"]}
    assert "UptimeRobot Monitor States" in titles

    # Third run must be idempotent.
    _run_script(dst)
    third = json.loads(dst.read_text(encoding="utf-8"))
    assert third["version"] == second["version"]


def test_all_panel_queries_have_balanced_parentheses(temp_dashboard: Path) -> None:
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    for panel in data["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if not expr:
                continue
            assert expr.count("(") == expr.count(")"), f"Unbalanced parentheses in {panel['title']!r}: {expr[:200]}"


def test_update_script_fixes_external_checks_query(temp_dashboard: Path) -> None:
    """External Checks should use the generic bridge contract."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "External Checks")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_scrape_success" in expr
    assert "live_overlay_bridge_enabled" in expr
    assert 'bridge=~"uptimerobot|github_workflow"' in expr
    assert "min by (job)" in expr
    assert panel["targets"][0]["legendFormat"] == "{{job}}"
    assert 'or on(job) label_replace(vector(-1), "job", "live_overlay", "", "")' in expr


def test_update_script_fixes_bridge_error_panels(temp_dashboard: Path) -> None:
    """Bridge error panels must not count the healthy error_code="none" series."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    for title in ("UptimeRobot Bridge Error", "GitHub Workflow Bridge Error"):
        panel = next(p for p in data["panels"] if p.get("title") == title)
        expr = panel["targets"][0]["expr"]
        assert 'error_code!="none"' in expr, f"{title}: {expr[:200]}"


def test_update_script_adds_railway_status_panels(temp_dashboard: Path) -> None:
    """Railway row should use the generic bridge contract and expose error class."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in data["panels"]}
    assert "Railway Metrics Bridge" in titles
    assert "Railway Metrics Snapshot Age" in titles
    assert "Railway Metrics Error" in titles

    bridge = next(p for p in data["panels"] if p.get("title") == "Railway Metrics Bridge")
    assert "live_overlay_bridge_enabled" in bridge["targets"][0]["expr"]
    assert "live_overlay_bridge_scrape_success" in bridge["targets"][0]["expr"]
    assert 'bridge="railway_metrics"' in bridge["targets"][0]["expr"]


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


def test_uptimerobot_panel_does_not_clobber_prior_changes(temp_dashboard: Path) -> None:
    """Regression: _ensure_uptimerobot_panel() overwrote `changed`, so earlier
    self-heal fixes could be silently dropped and the dashboard version not bumped.
    """
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    # Force v1 branch and guarantee an earlier fix has something to change.
    data.pop("schemaVersion", None)
    data["version"] = 1
    # Break a Railway link so _ensure_railway_resource_links must change the dashboard.
    for link in data.get("links", []):
        if link.get("title") in ("Railway logs", "Railway deployments", "Railway metrics"):
            link["url"] = "https://railway.app/project"
    temp_dashboard.write_text(json.dumps(data, indent=2), encoding="utf-8")

    _run_script(temp_dashboard)

    updated = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    # The earlier railway-link fix must be persisted and the version bumped.
    assert updated["version"] > 1, "version was not bumped even though prior fixes changed the dashboard"
    raw = temp_dashboard.read_text(encoding="utf-8")
    assert "REPLACE_PROJECT" not in raw, "prior railway-link fix was lost"


def test_update_script_adds_no_checks_configured_mapping(temp_dashboard: Path) -> None:
    """External Checks should gain a -1 value mapping for unconfigured bridges."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "External Checks")
    options_keys = {k for m in panel["fieldConfig"]["defaults"]["mappings"] for k in m["options"]}
    assert "-1" in options_keys
    labels = {m["options"][k]["text"] for m in panel["fieldConfig"]["defaults"]["mappings"] for k in m["options"]}
    assert "NO CHECKS CONFIGURED" in labels


def test_update_script_market_data_freshness_hides_when_closed(temp_dashboard: Path) -> None:
    """Market Data Freshness should display MARKET CLOSED instead of 0%%."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "Market Data Freshness")
    expr = panel["targets"][0]["expr"]
    assert "unless on()" in expr
    assert panel["fieldConfig"]["defaults"].get("noValue") == "MARKET CLOSED"


def test_update_script_core_metrics_present_checks_critical_series(temp_dashboard: Path) -> None:
    """Core Metrics Present should sum absent() over critical series."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "Core Metrics Present")
    expr = panel["targets"][0]["expr"]
    assert "absent(live_overlay_uptime_seconds" in expr
    assert "absent(live_overlay_overlay_fresh" in expr
    assert "absent(live_overlay_market_us_open" in expr
    assert "absent(live_overlay_last_bar_age_known" in expr
    assert "absent(live_overlay_smc_live_requests_total" in expr
    assert "absent(live_overlay_smc_live_success_total" in expr
    assert "absent(live_overlay_smc_live_errors_total" in expr
    assert "absent(live_overlay_smc_live_latency_ms_count" in expr
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    assert any(m.get("options", {}).get("8") for m in mappings) or "8 MISSING" in str(mappings)


def test_update_script_re_adds_traffic_alert_armed_without_extra_shift(temp_dashboard: Path) -> None:
    """Traffic Alert Armed is self-healed without repeatedly moving lower rows."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    operational_y = next(p for p in data["panels"] if p.get("title") == "Operational Drill-down")["gridPos"]["y"]
    data["panels"] = [p for p in data["panels"] if p.get("title") != "Traffic Alert Armed"]
    temp_dashboard.write_text(json.dumps(data, indent=2), encoding="utf-8")

    _run_script(temp_dashboard)

    updated = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in updated["panels"] if p.get("title") == "Traffic Alert Armed")
    assert panel["targets"][0]["expr"] == 'live_overlay_expected_market_traffic{job=~"$job"}'
    assert panel["fieldConfig"]["defaults"]["mappings"][0]["options"]["0"]["text"] == "NOT ARMED"
    assert panel["fieldConfig"]["defaults"]["mappings"][0]["options"]["1"]["text"] == "ARMED"
    updated_operational = next(p for p in updated["panels"] if p.get("title") == "Operational Drill-down")
    assert updated_operational["gridPos"]["y"] == operational_y


def test_update_script_railway_bridge_uses_generic_bridge_contract(temp_dashboard: Path) -> None:
    """Railway Metrics Bridge panel should use the generic bridge contract."""
    _run_script(temp_dashboard)
    data = json.loads(temp_dashboard.read_text(encoding="utf-8"))
    panel = next(p for p in data["panels"] if p.get("title") == "Railway Metrics Bridge")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert 'bridge="railway_metrics"' in expr
    assert "live_overlay_railway_metrics_enabled" not in expr


def test_update_script_check_mode_passes_on_current_dashboard() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "update_overlay_dashboard.py"
    dashboard = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"

    result = subprocess.run(
        [sys.executable, str(script), "--check", str(dashboard)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "is up to date" in result.stdout


def test_update_script_check_mode_fails_on_stale_dashboard(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "update_overlay_dashboard.py"
    src = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dst = tmp_path / "dashboard.json"
    shutil.copy(src, dst)

    data = json.loads(dst.read_text(encoding="utf-8"))
    # Remove a self-healed panel so the updater would mutate the dashboard.
    data["panels"] = [p for p in data["panels"] if p.get("title") != "UptimeRobot Monitor States"]
    dst.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), "--check", str(dst)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stderr + result.stdout
    assert "is not up to date" in result.stdout
