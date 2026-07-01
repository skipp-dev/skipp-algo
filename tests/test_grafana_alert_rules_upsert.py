"""Tests + guard rails for ``scripts/grafana_alert_rules_upsert.py``.

These tests are the safety net that keeps the Grafana alerting deploy
reproducible from the repo: they fail CI if ``alert-rules.yaml`` becomes
structurally invalid, if the upsert payload/endpoint regresses, or if the
live-news refresh workflow regresses to the ``--newsapi-only`` flag that
previously disabled the FMP / TradingView providers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "grafana_alert_rules_upsert.py"
ALERT_RULES = REPO / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
NEWSAPI_WORKFLOW = REPO / ".github" / "workflows" / "smc-live-newsapi-refresh.yml"


def _load():
    spec = importlib.util.spec_from_file_location("grafana_alert_rules_upsert", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["grafana_alert_rules_upsert"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# --------------------------------------------------------------------------- #
# PromQL gating anti-pattern linter (regression guard for the false-firing class)
# --------------------------------------------------------------------------- #

# Verbatim pre-fix expressions of the two production alerts that false-fired.
# The linter MUST flag both; the shipped rules MUST stay clean.
_HISTORICAL_BUGS = {
    "lo-request-rate-absent-open (bool comparison used as an `and` gate)": (
        'live_overlay_expected_market_traffic{job="live_overlay"} == 1 '
        'and on(job) live_overlay_market_us_open{job="live_overlay"} == 1 '
        'and on(job) live_overlay_uptime_seconds{job="live_overlay"} > bool 600 '
        'and on(job) rate(live_overlay_smc_live_requests_total{job="live_overlay"}[10m]) '
        '< bool 0.001'
    ),
    "sp-snapshot-missing (`or vector()` without `on()`)": (
        '(1 - signals_producer_open_prep_snapshot_loaded{job="signals_producer"}) '
        'or vector(1)'
    ),
}


@pytest.mark.parametrize("label,expr", list(_HISTORICAL_BUGS.items()))
def test_linter_flags_historical_gating_bugs(label: str, expr: str) -> None:
    assert mod.find_promql_gating_antipatterns(expr), f"linter missed: {label}"


def _promql_exprs():
    for group in mod.load_alert_groups(ALERT_RULES):
        for rule in group["rules"]:
            for node in rule.get("data", []):
                model = node.get("model", {})
                if node.get("datasourceUid") not in (None, "__expr__") and isinstance(
                    model.get("expr"), str
                ):
                    yield rule.get("uid"), model["expr"]


def test_all_alert_rules_free_of_gating_antipatterns() -> None:
    offenders = {
        uid: findings
        for uid, expr in _promql_exprs()
        if (findings := mod.find_promql_gating_antipatterns(expr))
    }
    assert not offenders, f"gating anti-patterns found: {offenders}"


def test_valid_gating_patterns_are_not_flagged() -> None:
    # bool comparison as the *value* (left) operand with a real filter gate.
    assert not mod.find_promql_gating_antipatterns(
        '(live_overlay_uptimerobot_monitors_down_total{job="live_overlay"} > bool 0) '
        'and on(job) (live_overlay_bridge_enabled{job="live_overlay",bridge="uptimerobot"} == 1)'
    )
    # label-safe `or on() vector()` fallback.
    assert not mod.find_promql_gating_antipatterns(
        '(signals_producer_watchlist_symbols{job="signals_producer"} == bool 0) or on() vector(1)'
    )
    # aggregation reduces the LHS to {} labels, so `or vector(0)` matches.
    assert not mod.find_promql_gating_antipatterns(
        'sum(increase(live_overlay_full_compute_cycle_errors{job="live_overlay"}[15m])) or vector(0)'
    )
    # multiplicative gating (the shipped fix form).
    assert not mod.find_promql_gating_antipatterns(
        'live_overlay_expected_market_traffic{job="live_overlay"} * '
        'live_overlay_market_us_open{job="live_overlay"} * '
        '(live_overlay_uptime_seconds{job="live_overlay"} > bool 600) * '
        '(rate(live_overlay_smc_live_requests_total{job="live_overlay"}[10m]) < bool 0.001)'
    )


def test_validator_rejects_gating_antipattern() -> None:
    bad = [
        {
            "name": "g",
            "folder": "F",
            "interval": "1m",
            "rules": [
                {
                    "uid": "x",
                    "title": "x",
                    "for": "5m",
                    "condition": "C",
                    "data": [
                        {
                            "refId": "A",
                            "datasourceUid": "grafanacloud-prom",
                            "model": {
                                "expr": 'foo{job="j"} == 1 and on(job) bar{job="j"} > bool 3'
                            },
                        },
                        {
                            "refId": "C",
                            "datasourceUid": "__expr__",
                            "model": {"type": "threshold"},
                        },
                    ],
                }
            ],
        }
    ]
    errors = mod.validate_alert_groups(bad)
    assert any("gating anti-pattern" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# parse_interval_seconds
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "expected"),
    [("1m", 60), ("5m", 300), ("30s", 30), ("1h", 3600), ("90", 90), (120, 120)],
)
def test_parse_interval_seconds_ok(value: Any, expected: int) -> None:
    assert mod.parse_interval_seconds(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "1x", 0, -5, True, None, 1.5])
def test_parse_interval_seconds_rejects_bad(value: Any) -> None:
    with pytest.raises(ValueError):
        mod.parse_interval_seconds(value)


# --------------------------------------------------------------------------- #
# validate_alert_groups against the real repo file
# --------------------------------------------------------------------------- #
def test_repo_alert_rules_are_structurally_valid() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    errors = mod.validate_alert_groups(groups)
    assert errors == [], "alert-rules.yaml structural errors:\n" + "\n".join(errors)


def test_repo_alert_rule_uids_are_globally_unique() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = [r["uid"] for g in groups for r in g["rules"]]
    assert len(uids) == len(set(uids))


def test_validate_flags_duplicate_uid_and_bad_refs() -> None:
    groups = [
        {
            "name": "g1",
            "folder": "F",
            "interval": "1m",
            "rules": [
                {
                    "uid": "dup",
                    "title": "ok rule",
                    "condition": "A",
                    "for": "0s",
                    "data": [{"refId": "A", "datasourceUid": "x", "model": {}}],
                },
                {
                    "uid": "dup",  # duplicate
                    "title": "bad ref",
                    "condition": "Z",  # not among refIds
                    "for": "0s",
                    "data": [{"refId": "A", "datasourceUid": "x", "model": {}}],
                },
            ],
        }
    ]
    errors = mod.validate_alert_groups(groups)
    joined = "\n".join(errors)
    assert "duplicate uid 'dup'" in joined
    assert "condition 'Z'" in joined


def test_validate_flags_missing_fields() -> None:
    errors = mod.validate_alert_groups(
        [{"name": "", "folder": "", "interval": "nope", "rules": []}]
    )
    assert any("missing/empty 'name'" in e for e in errors)
    assert any("'rules' must be a non-empty list" in e for e in errors)


# --------------------------------------------------------------------------- #
# payload construction
# --------------------------------------------------------------------------- #
def test_build_rule_group_payload_shape() -> None:
    group = mod.load_alert_groups(ALERT_RULES)[0]
    payload = mod.build_rule_group_payload(group, "folder-uid-123")
    assert payload["folderUid"] == "folder-uid-123"
    assert payload["title"] == group["name"]
    assert isinstance(payload["interval"], int) and payload["interval"] > 0
    assert payload["rules"], "expected at least one rule"
    rule = payload["rules"][0]
    for key in ("uid", "title", "condition", "data", "for", "folderUID", "ruleGroup", "orgID", "noDataState", "execErrState"):
        assert key in rule, f"missing {key} in provisioned rule"
    assert rule["folderUID"] == "folder-uid-123"
    assert rule["ruleGroup"] == group["name"]
    assert rule["noDataState"] == mod.DEFAULT_NO_DATA_STATE
    assert rule["execErrState"] == mod.DEFAULT_EXEC_ERR_STATE


def test_build_rule_group_payload_sets_threshold_expression_refs() -> None:
    """Grafana provisioning API requires threshold nodes to name their input ref."""
    groups = mod.load_alert_groups(ALERT_RULES)
    threshold_nodes = []
    for group in groups:
        payload = mod.build_rule_group_payload(group, "folder-uid-123")
        for rule in payload["rules"]:
            for node in rule["data"]:
                model = node.get("model", {})
                if node.get("datasourceUid") == "__expr__" and model.get("type") == "threshold":
                    threshold_nodes.append((rule["uid"], model))

    assert threshold_nodes, "expected threshold expression nodes in alert rules"
    for uid, model in threshold_nodes:
        expected = model["conditions"][0]["query"]["params"][0]
        assert model.get("expression") == expected, uid


# --------------------------------------------------------------------------- #
# HTTP layer with mocked urlopen
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_resolve_folder_uid_matches_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    def fake_urlopen(req, timeout=0):
        assert req.get_method() == "GET"
        assert "/api/folders" in req.full_url
        return _FakeResp(json.dumps([{"title": "SMC Live Overlay", "uid": "abc"}]).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.resolve_folder_uid("SMC Live Overlay", "key") == "abc"


def test_resolve_folder_uid_creates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    calls: list[tuple[str, str]] = []

    def fake_urlopen(req, timeout=0):
        calls.append((req.get_method(), req.full_url))
        if req.get_method() == "GET":
            return _FakeResp(json.dumps([]).encode())
        return _FakeResp(json.dumps({"uid": "new-uid"}).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.resolve_folder_uid("New Folder", "key") == "new-uid"
    assert calls[0][0] == "GET"
    assert calls[1][0] == "POST"


def test_upsert_group_uses_rule_group_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout=0):
        method = req.get_method()
        if method == "GET":
            return _FakeResp(json.dumps([{"title": "SMC Live Overlay", "uid": "fuid"}]).encode())
        captured["method"] = method
        captured["url"] = req.full_url
        captured["provenance"] = req.headers.get("X-disable-provenance")
        captured["body"] = json.loads(req.data.decode())
        return _FakeResp(b"")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    group = mod.load_alert_groups(ALERT_RULES)[0]
    written = mod.upsert_group(group, "key")
    assert written == len(group["rules"])
    assert captured["method"] == "PUT"
    assert f"/api/v1/provisioning/folder/fuid/rule-groups/{group['name']}" in captured["url"]
    assert captured["provenance"] == "true"
    assert captured["body"]["folderUid"] == "fuid"


def test_api_key_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mod.ENV_API_KEY, "env-token")
    assert mod._api_key() == "env-token"


def test_main_dry_run_validates_without_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a: object, **k: object) -> None:  # network must not be touched
        raise AssertionError("network call during --dry-run")

    monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
    rc = mod.main(["--dry-run"])
    assert rc == 0
    assert "Validated" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Regression guard: the live-news refresh workflow must keep FMP / TradingView on
# --------------------------------------------------------------------------- #
def test_newsapi_refresh_workflow_keeps_fmp_and_tradingview_enabled() -> None:
    text = NEWSAPI_WORKFLOW.read_text(encoding="utf-8")
    # Inspect only real shell lines (ignore YAML comments, which may mention the
    # historical flag) and reject an *active* ``--newsapi-only`` export argument.
    active_lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert not any("--newsapi-only" in ln for ln in active_lines), (
        "smc-live-newsapi-refresh.yml must not run the export with --newsapi-only "
        "(that disables FMP + TradingView despite active subscriptions)."
    )
    active_text = "\n".join(active_lines)
    # The active export command must enable Benzinga and inject both API keys.
    assert "--skip-benzinga" not in active_text
    assert "FMP_API_KEY" in active_text
    assert "BENZINGA_API_KEY" in active_text


# --------------------------------------------------------------------------- #
# Dashboard-review regression guards
# --------------------------------------------------------------------------- #
def test_alert_workers_degraded_and_overlay_stale_include_job_filter() -> None:
    """All live-overlay alerts must scope to job="live_overlay"."""
    groups = mod.load_alert_groups(ALERT_RULES)
    required_uids = {"lo-workers-degraded", "lo-overlay-stale"}
    rules_by_uid = {rule["uid"]: rule for group in groups for rule in group["rules"]}
    assert required_uids <= rules_by_uid.keys()
    for uid in required_uids:
        expr = rules_by_uid[uid]["data"][0]["model"]["expr"]
        assert 'job="live_overlay"' in expr, f"{uid} is missing job filter: {expr}"


def test_alert_rules_include_bridge_contract_missing() -> None:
    """Critical alert must fire when a generic bridge contract is absent."""
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-bridge-contract-missing" in uids
    rule = next(
        r for g in groups for r in g["rules"] if r["uid"] == "lo-bridge-contract-missing"
    )
    exprs = [d["model"]["expr"] for d in rule["data"] if d.get("refId") in {"A", "B", "C"}]
    families = (
        "live_overlay_bridge_enabled",
        "live_overlay_bridge_configured",
        "live_overlay_bridge_scrape_success",
        "live_overlay_bridge_error_info",
        "live_overlay_bridge_last_success_age_seconds",
        "live_overlay_bridge_last_scrape_duration_seconds",
    )
    for bridge in ("uptimerobot", "github_workflow", "railway_metrics"):
        bridge_expr = next((e for e in exprs if f'bridge="{bridge}"' in e), "")
        assert bridge_expr, f"missing bridge {bridge}"
        normalized = " ".join(bridge_expr.split())
        for family in families:
            expected = (
                f'sum(absent({family}{{job="live_overlay",bridge="{bridge}"}})'
                " or on() vector(0))"
            )
            assert expected in normalized, f"missing {family} for {bridge}"
    assert all(" or vector(0)" not in e for e in exprs)
    assert sum(e.count("sum(absent(live_overlay_bridge_") for e in exprs) == 18
    assert rule["labels"]["severity"] == "critical"


def test_alert_rules_gate_external_bridge_alerts_on_generic_contract() -> None:
    """External bridge alerts should not use legacy bridge-enabled gauges."""
    groups = mod.load_alert_groups(ALERT_RULES)
    rules_by_uid = {rule["uid"]: rule for group in groups for rule in group["rules"]}
    expected = {
        "lo-uptimerobot-snapshot-stale": "uptimerobot",
        "lo-uptimerobot-monitor-count-mismatch": "uptimerobot",
        "lo-uptimerobot-monitor-down": "uptimerobot",
        "lo-github-workflow-snapshot-stale": "github_workflow",
    }

    for uid, bridge in expected.items():
        expr = rules_by_uid[uid]["data"][0]["model"]["expr"]
        assert f'live_overlay_bridge_enabled{{job="live_overlay",bridge="{bridge}"}}' in expr
        assert "live_overlay_uptimerobot_bridge_enabled" not in expr
        assert "live_overlay_github_workflow_bridge_enabled" not in expr


def test_alert_rules_include_tradingview_credential_age() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-tradingview-credential-age-high" in uids
    rule = next(
        r for g in groups for r in g["rules"]
        if r["uid"] == "lo-tradingview-credential-age-high"
    )
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_tradingview_credential_age_hours" in expr
    assert 'job="live_overlay"' in expr


def test_alert_rules_include_ingest_queue_lag() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-ingest-queue-lag-high" in uids
    rule = next(
        r for g in groups for r in g["rules"] if r["uid"] == "lo-ingest-queue-lag-high"
    )
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_feed_ingest_queue_lag_ms_max" in expr
    assert rule["labels"]["severity"] == "warning"


def test_alert_rules_include_daemon_restarts_high() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-daemon-restarts-high" in uids
    rule = next(
        r for g in groups for r in g["rules"] if r["uid"] == "lo-daemon-restarts-high"
    )
    expr = rule["data"][0]["model"]["expr"]
    assert "increase(live_overlay_daemon_restarts_total" in expr
    assert "[24h]" in expr
    assert rule["labels"]["severity"] == "high"


def test_build_provisioned_rule_adds_default_relative_time_range() -> None:
    """Queries without a usable relativeTimeRange must inherit the Grafana default."""
    group = mod.load_alert_groups(ALERT_RULES)[0]
    rule = group["rules"][0]
    # ensure the fixture itself does not carry the field for this assertion
    original_data = rule["data"]
    rule["data"] = [{**node, "relativeTimeRange": {}} for node in original_data]
    try:
        payload = mod.build_provisioned_rule(rule, group, "folder-uid-123")
        for node in payload["data"]:
            assert node["relativeTimeRange"] == {"from": 300, "to": 0}
    finally:
        rule["data"] = original_data
