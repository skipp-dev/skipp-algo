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
