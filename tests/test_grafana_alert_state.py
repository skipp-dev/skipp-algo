"""Unit tests for the read-only Grafana alert-state reader.

The pure summarizers take already-loaded API payloads, so these tests run
hermetically — no network, no keychain (mirrors the build_snapshot test
pattern of scripts/build_evidence_freshness_snapshot.py).
"""
from __future__ import annotations

from scripts.grafana_alert_state import (
    summarize_active_alerts,
    summarize_rule_states,
)

_AM_ALERTS = [
    {
        "labels": {"alertname": "CI full-suite red on main", "severity": "warning"},
        "status": {"state": "active"},
        "startsAt": "2026-07-22T08:58:00.000Z",
    },
    {
        "labels": {"alertname": "PRE-A0 shadow snapshots missing under live load", "severity": "critical"},
        "status": {"state": "active"},
        "startsAt": "2026-07-22T11:08:00.000Z",
    },
    {
        # DatasourceNoData style instance without severity — must not crash
        "labels": {"alertname": "Odd instance"},
        "status": {"state": "suppressed"},
        "startsAt": "2026-07-22T00:00:00.000Z",
    },
]

_PROM_RULES = {
    "data": {
        "groups": [
            {
                "name": "g1",
                "rules": [
                    {"name": "Feed symbology drops sustained", "state": "inactive", "health": "ok", "type": "alerting"},
                    {"name": "SMC micro-profile library data stale", "state": "firing", "health": "ok", "type": "alerting"},
                    {"name": "Some recording rule", "type": "recording"},
                ],
            },
            {
                "name": "g2",
                "rules": [
                    {"name": "Overlay data lost after restart (market closed)", "state": "pending", "health": "error", "type": "alerting"},
                ],
            },
        ]
    }
}


def test_summarize_active_alerts_sorts_critical_first_and_tolerates_missing_severity() -> None:
    rows = summarize_active_alerts(_AM_ALERTS)
    assert [r["alertname"] for r in rows][:2] == [
        "PRE-A0 shadow snapshots missing under live load",
        "CI full-suite red on main",
    ]
    assert rows[0]["severity"] == "critical"
    assert rows[-1]["severity"] == "-"  # missing severity renders as '-', no crash
    assert all(set(r) >= {"alertname", "severity", "state", "startsAt"} for r in rows)


def test_summarize_rule_states_skips_recording_rules_and_filters() -> None:
    rows = summarize_rule_states(_PROM_RULES)
    names = [r["name"] for r in rows]
    assert "Some recording rule" not in names, "recording rules are not alert states"
    assert len(rows) == 3

    firing_or_pending = summarize_rule_states(_PROM_RULES, only_active=True)
    assert {r["name"] for r in firing_or_pending} == {
        "SMC micro-profile library data stale",
        "Overlay data lost after restart (market closed)",
    }

    filtered = summarize_rule_states(_PROM_RULES, name_filter="micro-profile")
    assert [r["name"] for r in filtered] == ["SMC micro-profile library data stale"]
    assert filtered[0]["state"] == "firing"


def test_summarize_rule_states_reports_unhealthy_rules_even_when_inactive() -> None:
    payload = {
        "data": {"groups": [{"name": "g", "rules": [
            {"name": "Broken expr rule", "state": "inactive", "health": "error", "type": "alerting"},
        ]}]}
    }
    rows = summarize_rule_states(payload, only_active=True)
    assert [r["name"] for r in rows] == ["Broken expr rule"], (
        "health=error must surface in the active view — an unevaluable rule "
        "is operationally worse than a firing one"
    )
