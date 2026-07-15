"""Guard: every monitoring metric the exporter emits has a consumer.

The 2026-06/07 blind-spot had a precise shape: the daemon *exported*
per-workflow health gauges (``live_overlay_github_workflow_latest_success`` /
``phase_code`` / ``latest_age_seconds``) but **zero alert rules referenced
them**, so ``adr0023-magnitude-shadow-daily`` could go red for weeks while
Grafana stayed green. This test makes that class of gap fail CI:

* Part A — the per-workflow status signals MUST each be used by >= 1 alert rule.
* Part B — the evidence-chain freshness signals MUST each be used by >= 1 alert.
* Part C — no ``live_overlay_evidence_*`` / per-workflow metric may be emitted
  without at least one consumer (alert rule OR dashboard panel), so a future
  metric added with no watcher fails here instead of silently going invisible.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_METRICS_PY = _REPO_ROOT / "services" / "live_overlay_daemon" / "metrics.py"
_GRAFANA = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana"
_ALERT_RULES = _GRAFANA / "alert-rules.yaml"
_DASHBOARD = _GRAFANA / "dashboard.json"
# Both dashboards are consumers: a metric charted only on the experiments board
# still counts as watched, so scan both (the guard previously missed it).
_DASHBOARDS = (_DASHBOARD, _GRAFANA / "dashboard-signals-experiments.json")

# Per-workflow status signals that had zero alert coverage (the exact gap).
_WORKFLOW_SIGNAL_METRICS = (
    "live_overlay_github_workflow_latest_success",
    "live_overlay_github_workflow_phase_code",
    "live_overlay_github_workflow_latest_age_seconds",
)

# Evidence-chain freshness signals that MUST alert (the silent-freeze detectors).
_EVIDENCE_SIGNAL_METRICS = (
    "live_overlay_evidence_freshness_loaded",
    "live_overlay_evidence_freshness_snapshot_age_seconds",
    "live_overlay_evidence_ledger_age_seconds",
    "live_overlay_evidence_audit_branch_age_seconds",
    "live_overlay_evidence_wsh_age_seconds",
)

# Credential / API-key health signals that MUST alert. These gauges were charted
# but had ZERO alert coverage while the probe's only alarm (a GitHub issue) was
# inert (repo Issues disabled) — an expired key surfaced nowhere. The per-probe
# ``_valid`` names are built by f-string in metrics.py, so _METRIC_RE cannot
# auto-discover them (it stops at ``{``); they are pinned explicitly like Part A/B.
_CREDENTIAL_SIGNAL_METRICS = (
    "live_overlay_credential_health_fmp_api_key_valid",
    "live_overlay_credential_health_databento_api_key_valid",
    "live_overlay_credential_health_databento_delivery_valid",
    "live_overlay_credential_health_benzinga_key_valid",
    "live_overlay_credential_health_finnhub_api_key_valid",
    "live_overlay_credential_health_github_pat_validity_valid",
    "live_overlay_credential_health_tv_storage_state_age_valid",
    "live_overlay_credential_health_snapshot_age_seconds",
)

# Provider-usage FEED-HEALTH signals that MUST alert. The daemon exported
# ``live_overlay_provider_usage_loaded`` and ``...snapshot_age_seconds`` but
# nothing consumed them, so a missing/frozen ingest snapshot silently starved
# the FMP-quota + provider-429 alerts (all computed off that same snapshot)
# while they stayed on ``noDataState: OK``. Pin the feed-health gauges here so a
# dropped stale/missing rule fails CI instead of reopening the blind spot.
_PROVIDER_USAGE_SIGNAL_METRICS = (
    "live_overlay_provider_usage_loaded",
    "live_overlay_provider_usage_snapshot_age_seconds",
)

# Pine-library version-drift signals that MUST alert (#3599/#3603). The daemon
# exports the snapshot loaded/age gauges, the top-level drift rollup, and the
# facade-probe health; if any loses its alert rule a stale import pin (the
# ~4-month micro_profiles /1-vs-/152 blind spot) goes unwatched again. `_METRIC_RE`
# only auto-discovers evidence/workflow families, so pin these explicitly.
_PINE_LIBRARY_SIGNAL_METRICS = (
    "live_overlay_pine_library_snapshot_loaded",
    "live_overlay_pine_library_snapshot_age_seconds",
    "live_overlay_pine_library_any_drift",
    "live_overlay_pine_library_facade_ok",
)

_METRIC_RE = re.compile(r"live_overlay_(?:evidence|github_workflow)_[a-z0-9_]+")


def _alert_expr_text() -> str:
    doc = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    exprs: list[str] = []
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            for node in rule.get("data", []):
                expr = (node.get("model") or {}).get("expr")
                if isinstance(expr, str):
                    exprs.append(expr)
    return "\n".join(exprs)


def _dashboard_expr_text() -> str:
    exprs: list[str] = []
    for dashboard in _DASHBOARDS:
        if not dashboard.exists():
            continue
        doc = json.loads(dashboard.read_text(encoding="utf-8"))
        for panel in doc.get("panels", []):
            for target in panel.get("targets", []) or []:
                expr = target.get("expr")
                if isinstance(expr, str):
                    exprs.append(expr)
    return "\n".join(exprs)


def _emitted_metrics() -> set[str]:
    """Metric names the exporter emits, discovered from metrics.py source.

    f-string fragments (a name interrupted by ``{...}``) end up with a trailing
    underscore after the regex stops at ``{`` — those are dropped; only fully
    literal metric names are asserted (which is all the evidence + per-workflow
    status metrics this guard cares about).
    """
    source = _METRICS_PY.read_text(encoding="utf-8")
    return {m for m in _METRIC_RE.findall(source) if not m.endswith("_")}


def test_per_workflow_signals_have_alert_coverage() -> None:
    """The exact 2026-06/07 gap: per-workflow health metrics must alert."""
    alerts = _alert_expr_text()
    missing = [m for m in _WORKFLOW_SIGNAL_METRICS if m not in alerts]
    assert not missing, (
        "per-workflow status metrics exist but NO alert rule references them "
        f"(the silent-red-cron gap): {missing}"
    )


def test_evidence_signals_have_alert_coverage() -> None:
    alerts = _alert_expr_text()
    missing = [m for m in _EVIDENCE_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"evidence freshness signals lack alert coverage: {missing}"


def test_credential_signals_have_alert_coverage() -> None:
    """Every API-key health gauge + the snapshot-staleness gauge must alert.

    Prevents the credential-alerting gap from silently reopening: a new probe or
    a dropped alert rule that leaves a key gauge unwatched fails CI here.
    """
    alerts = _alert_expr_text()
    missing = [m for m in _CREDENTIAL_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"credential/API-key health signals lack alert coverage: {missing}"


def test_provider_usage_feed_health_signals_have_alert_coverage() -> None:
    """Provider-usage feed-health gauges must alert, so a missing/frozen ingest
    snapshot cannot silently starve the FMP-quota + provider-429 alerts.
    """
    alerts = _alert_expr_text()
    missing = [m for m in _PROVIDER_USAGE_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"provider-usage feed-health signals lack alert coverage: {missing}"


def test_pine_library_signals_have_alert_coverage() -> None:
    """Every Pine-library version-drift health gauge must alert, so a stale
    import pin or a frozen/blind facade probe cannot silently reopen the
    #3599/#3603 blind spot."""
    alerts = _alert_expr_text()
    missing = [m for m in _PINE_LIBRARY_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"pine-library version-drift signals lack alert coverage: {missing}"


def test_no_emitted_monitoring_metric_is_unconsumed() -> None:
    """Every emitted evidence/workflow metric must be alerted OR charted."""
    consumers = _alert_expr_text() + "\n" + _dashboard_expr_text()
    emitted = _emitted_metrics()
    # Sanity: discovery actually found the families (guards against a rename
    # silently emptying the set and making this test vacuously pass).
    assert any(m.startswith("live_overlay_evidence_") for m in emitted), emitted
    orphans = sorted(m for m in emitted if m not in consumers)
    assert not orphans, (
        "these monitoring metrics are emitted but referenced by no alert rule "
        f"and no dashboard panel — they are invisible: {orphans}"
    )


def test_sweep_trap_shadow_no_data_state_has_alert_coverage() -> None:
    """The gt-0-inert hole: a missing/unreadable snapshot (and the committed
    no-data seed) yields age_known=0 AND stale=0, so the gt-0 stale rule stays
    green with zero data. The dedicated age-unknown rule must exist, target the
    age_known gauge and use the `== bool 0` form (a bare `== 0` returns 0 and a
    gt-0 threshold reads 0>0=false — inert)."""
    rules = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    exprs: dict[str, str] = {}
    for group in rules.get("groups", []):
        for rule in group.get("rules", []):
            for query in rule.get("data", []):
                expr = str((query.get("model") or {}).get("expr", ""))
                if expr:
                    exprs[str(rule.get("uid", ""))] = exprs.get(str(rule.get("uid", "")), "") + expr
    assert "lo-sweep-trap-shadow-age-unknown" in exprs
    expr = exprs["lo-sweep-trap-shadow-age-unknown"]
    assert "live_overlay_sweep_trap_shadow_snapshot_age_known" in expr
    assert "== bool 0" in expr


# Every evidence-chain age axis and the age_known gauge that says whether the
# age means anything. `_coerce` (evidence_freshness_bridge) hard-codes
# loaded=1.0 and tolerates missing keys, so a snapshot that PARSES but carries
# no date yields age_known=0 AND age_seconds=0 -- every `age > threshold` rule
# reads 0>N=false and lo-evidence-snapshot-unloadable reads loaded<1=false.
# Both stay green with zero data. That shape is not hypothetical: the GitHub
# Contents-API envelope produced exactly it ("EMPTY snapshot with loaded=1,
# keeping the stale alert silently green" -- _fetch_url, post-review finding
# 1). The cause was fixed; these rules close the DETECTION gap.
_EVIDENCE_AGE_UNKNOWN_RULES = (
    ("lo-evidence-snapshot-age-unknown", "live_overlay_evidence_freshness_snapshot_age_known"),
    ("lo-evidence-ledger-age-unknown", "live_overlay_evidence_ledger_age_known"),
    ("lo-evidence-audit-branch-age-unknown", "live_overlay_evidence_audit_branch_age_known"),
    ("lo-evidence-wsh-age-unknown", "live_overlay_evidence_wsh_age_known"),
)


def _rule_exprs() -> dict[str, str]:
    rules = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    exprs: dict[str, str] = {}
    for group in rules.get("groups", []):
        for rule in group.get("rules", []):
            uid = str(rule.get("uid", ""))
            for query in rule.get("data", []):
                expr = str((query.get("model") or {}).get("expr", ""))
                if expr:
                    exprs[uid] = exprs.get(uid, "") + expr
    return exprs


def test_evidence_age_unknown_states_have_alert_coverage() -> None:
    """Each evidence age axis needs an age-unknown rule the stale rule cannot be.

    Stale is only computable once an age is KNOWN, so `age > threshold` can
    never fire on age_known=0 (it reads 0>N=false). Each axis therefore needs a
    dedicated rule on its age_known gauge, gated on `loaded` so an unloadable
    snapshot pages once (lo-evidence-snapshot-unloadable) rather than twice.
    """
    exprs = _rule_exprs()
    for uid, known_metric in _EVIDENCE_AGE_UNKNOWN_RULES:
        assert uid in exprs, f"{uid} is missing — the age-unknown state is unwatched"
        expr = exprs[uid]
        assert known_metric in expr, f"{uid} must target {known_metric}, got: {expr}"
        # `== bool 0` is mandatory: a bare `== 0` returns the value 0 and the
        # gt-0 threshold reads 0>0=false — inert (the gt-0-inert class).
        assert "== bool 0" in expr, f"{uid} must use `== bool 0` (bare `== 0` is inert): {expr}"
        assert "live_overlay_evidence_freshness_loaded" in expr, (
            f"{uid} must gate on the loaded gauge so an unloadable snapshot does not "
            f"double-page with lo-evidence-snapshot-unloadable: {expr}"
        )


def test_evidence_ledger_age_unknown_does_not_double_page_with_empty() -> None:
    """lo-evidence-ledger-empty already owns rows==0, so the ledger age-unknown
    rule must gate on rows>0 and cover only the state neither -stale (needs a
    KNOWN age) nor -empty (needs rows==0) can see."""
    expr = _rule_exprs()["lo-evidence-ledger-age-unknown"]
    assert "live_overlay_evidence_ledger_rows" in expr, expr
    assert "> bool 0" in expr, expr


def test_dashboard_age_panels_gate_on_age_known() -> None:
    """An age panel must not render an UNKNOWN age as a misleading `0`.

    `metrics.py` emits age_seconds=0.0 when the age is unknown and publishes the
    truth in a companion age_known gauge. A panel that plots age_seconds alone
    shows `0` — "perfectly fresh" — for "no data at all", and its `noValue`
    never fires because the series exists. "Magnitude Ledger Age (days)" is a
    stat with a red-at-3-days threshold, so unknown rendered as a GREEN 0.
    Gating on age_known empties the series instead, so noValue shows N/A.
    """
    panels_by_title = {}
    for dashboard in _DASHBOARDS:
        if not dashboard.exists():
            continue
        doc = json.loads(dashboard.read_text(encoding="utf-8"))
        for panel in doc.get("panels", []):
            panels_by_title[str(panel.get("title", ""))] = panel

    expected = {
        "Magnitude Ledger Age (days)": {
            "live_overlay_evidence_ledger_age_seconds": "live_overlay_evidence_ledger_age_known",
        },
        "Evidence Chain Age (days)": {
            "live_overlay_evidence_ledger_age_seconds": "live_overlay_evidence_ledger_age_known",
            "live_overlay_evidence_audit_branch_age_seconds": (
                "live_overlay_evidence_audit_branch_age_known"
            ),
            "live_overlay_evidence_wsh_age_seconds": "live_overlay_evidence_wsh_age_known",
            "live_overlay_evidence_freshness_snapshot_age_seconds": (
                "live_overlay_evidence_freshness_snapshot_age_known"
            ),
        },
        "News Snapshot Age": {
            "live_overlay_provider_news_snapshot_age_seconds": (
                "live_overlay_provider_news_snapshot_age_known"
            ),
        },
    }

    for title, axes in expected.items():
        panel = panels_by_title.get(title)
        assert panel is not None, f"panel {title!r} vanished — update this guard"
        exprs = [
            str(t.get("expr", ""))
            for t in (panel.get("targets") or [])
            if isinstance(t.get("expr"), str)
        ]
        for age_metric, known_metric in axes.items():
            using = [e for e in exprs if age_metric in e]
            assert using, f"{title!r} no longer plots {age_metric} — update this guard"
            for expr in using:
                assert known_metric in expr, (
                    f"{title!r} plots {age_metric} without gating on {known_metric}: an "
                    f"unknown age renders as a misleading 0. Got: {expr}"
                )
        no_value = (panel.get("fieldConfig") or {}).get("defaults", {}).get("noValue")
        assert no_value, (
            f"{title!r} gates on age_known (so an unknown age yields an EMPTY series) but "
            "sets no noValue text — the panel would render blank instead of N/A"
        )


def test_news_snapshot_stale_alert_gates_on_age_known() -> None:
    """The news snapshot stale rule must not read age_seconds=0 as fresh.

    A loaded snapshot without a timestamp exports age_known=0 and
    age_seconds=0. Without an age_known gate the stale rule's
    `age_seconds > 10800` reads false (0 > threshold) and the dashboard shows
    a perfectly fresh 0 while the producer heartbeat is actually unknown.
    """
    expr = _rule_exprs()["lo-news-snapshot-stale"]
    assert "live_overlay_provider_news_snapshot_age_known" in expr, (
        "lo-news-snapshot-stale must gate on age_known so an unknown timestamp "
        f"does not masquerade as fresh. Got: {expr}"
    )


_AGE_UNKNOWN_RULES = (
    # (rule_uid, loaded_metric, age_known_metric)
    (
        "lo-news-snapshot-age-unknown",
        "live_overlay_provider_news_snapshot_loaded",
        "live_overlay_provider_news_snapshot_age_known",
    ),
    (
        "lo-pine-library-snapshot-age-unknown",
        "live_overlay_pine_library_snapshot_loaded",
        "live_overlay_pine_library_snapshot_age_known",
    ),
    (
        "lo-provider-usage-snapshot-age-unknown",
        "live_overlay_provider_usage_loaded",
        "live_overlay_provider_usage_snapshot_age_known",
    ),
)


@pytest.mark.parametrize("uid,loaded_metric,age_known_metric", _AGE_UNKNOWN_RULES)
def test_age_unknown_alert_coverage(
    uid: str, loaded_metric: str, age_known_metric: str
) -> None:
    """A loaded-but-undated snapshot needs its own alert.

    The unloadable rule owns loaded==0; the stale rule needs a known age. The
    loaded-but-undated state (age_known=0, age_seconds=0) is invisible to both
    unless a dedicated rule targets the age_known gauge with the `== bool 0`
    form (bare `== 0` is inert behind a gt-0 threshold).
    """
    exprs = _rule_exprs()
    assert uid in exprs, f"missing rule for loaded-but-undated snapshot: {uid}"
    expr = exprs[uid]
    assert age_known_metric in expr, (
        f"{uid} must target {age_known_metric}, got: {expr}"
    )
    assert loaded_metric in expr, (
        f"{uid} must gate on {loaded_metric} to avoid double-paging with the "
        f"unloadable rule, got: {expr}"
    )
    assert "== bool 0" in expr, (
        f"{uid} must use `== bool 0` (bare `== 0` is inert): {expr}"
    )
