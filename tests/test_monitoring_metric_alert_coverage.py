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
_ALERT_RULES = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
_DASHBOARD = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"

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
    doc = json.loads(_DASHBOARD.read_text(encoding="utf-8"))
    exprs: list[str] = []
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
