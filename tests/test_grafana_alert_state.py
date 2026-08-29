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


# ---------------------------------------------------------------------------
# 2026-08-15 sweep finding (Population C): schema drift or an empty 200 body
# read as "0 firing / 0 rules" — indistinguishable from a healthy quiet
# system, in the exact tool the session-start Betriebszustand check relies
# on. Absence of the structure is loud now; the honest quiet is a PRESENT
# empty list from the API.
# ---------------------------------------------------------------------------

import pytest


def test_missing_data_groups_is_loud_not_all_healthy() -> None:
    for broken in ({}, {"data": None}, {"data": {}}, {"status": "success"}):
        with pytest.raises(ValueError, match="refusing to report"):
            summarize_rule_states(broken)


def test_a_present_but_empty_groups_list_is_the_honest_quiet() -> None:
    assert summarize_rule_states({"data": {"groups": []}}) == []
    assert summarize_rule_states({"data": {"groups": None}}) == []


# --------------------------------------------------------------------------
# Zustandshistorie (2026-08-29): "hat der Alarm gefeuert?"
# --------------------------------------------------------------------------

import datetime as dt

from scripts.grafana_alert_state import decode_history, silent_pending_rules


def _hist(*ereignisse):
    """Eine Antwort in der ECHTEN Form: drei Spalten, `schema` null.

    Spalte 2 traegt bewusst ANDERE Daten (Stream-Labels), damit ein Leser, der
    die letzte Spalte greift, hier auffaellt statt plausibel Unsinn zu liefern.
    """
    basis = int(dt.datetime(2026, 8, 29, 7, 0, tzinfo=dt.UTC).timestamp() * 1000)
    zeiten = [basis + i * 60_000 for i in range(len(ereignisse))]
    labels = [{"from": "state-history", "org_id": "1818507"} for _ in ereignisse]
    return {"schema": None, "data": {"values": [zeiten, list(ereignisse), labels]}}


def test_history_is_decoded_from_the_event_column_not_the_stream_labels() -> None:
    """Die Falle, die am 2026-08-29 eine Auswertung wertlos machte.

    Der naheliegende Griff ist die LETZTE Spalte — die traegt aber Stream-
    Metadaten. Wer sie liest, bekommt ueberall `?` und schliesst daraus "keine
    Wechsel", obwohl es 34 waren. Eine leere Auswertung aus einer
    missverstandenen Antwort ist die gefaehrlichste Ausgabe dieses Lesers.
    """
    ereignisse = decode_history(_hist(
        {"ruleTitle": "CI full-suite red on main", "previous": "Normal", "current": "Pending"},
    ))
    assert len(ereignisse) == 1
    assert ereignisse[0]["rule"] == "CI full-suite red on main"
    assert ereignisse[0]["previous"] == "Normal"
    assert ereignisse[0]["current"] == "Pending"
    assert ereignisse[0]["ts"].startswith("2026-08-29T07:00:00")


def test_an_empty_body_raises_instead_of_reading_as_nothing_happened() -> None:
    """Ein leerer Body darf nicht als Ruhe durchgehen."""
    with pytest.raises(ValueError):
        decode_history(None)


def test_an_unexpected_shape_raises_instead_of_returning_empty() -> None:
    """Weniger als zwei Spalten heisst: nicht verstanden, nicht 'nichts da'."""
    with pytest.raises(ValueError):
        decode_history({"data": {"values": [[1, 2, 3]]}})
    with pytest.raises(ValueError):
        decode_history({"data": {}})


def test_a_rule_that_reached_pending_but_never_alerting_is_flagged() -> None:
    """Der eigentliche Zweck: gesehen und trotzdem stumm.

    Gemessen am 2026-08-29: "CI full-suite red on main" ging 07:46:30Z auf
    Pending und 08:33:30Z zurueck — 47 Minuten bei `for = 2h`. Die Regel war
    nicht blind, ihr Schwellwert war laenger als der Vorfall. Im Live-Zustand
    ist davon nichts zu sehen.
    """
    wechsel = decode_history(_hist(
        {"ruleTitle": "CI full-suite red on main", "previous": "Normal", "current": "Pending"},
        {"ruleTitle": "CI full-suite red on main", "previous": "Pending", "current": "Normal"},
    ))
    stumm = silent_pending_rules(wechsel)
    assert [s["rule"] for s in stumm] == ["CI full-suite red on main"]
    assert stumm[0]["pending_episodes"] == 1
    assert stumm[0]["reached_alerting"] is False


def test_a_rule_that_did_reach_alerting_is_not_flagged() -> None:
    """Gegenprobe: wer gefeuert hat, ist nicht stumm — sonst waere die Aussage vakuum."""
    wechsel = decode_history(_hist(
        {"ruleTitle": "Laut", "previous": "Normal", "current": "Pending"},
        {"ruleTitle": "Laut", "previous": "Pending", "current": "Alerting"},
        {"ruleTitle": "Laut", "previous": "Alerting", "current": "Normal"},
    ))
    assert silent_pending_rules(wechsel) == []


def test_a_rule_that_never_left_normal_is_not_flagged() -> None:
    wechsel = decode_history(_hist(
        {"ruleTitle": "Ruhig", "previous": "Normal", "current": "Normal (NoData)"},
    ))
    assert silent_pending_rules(wechsel) == []


def test_a_missing_rule_title_is_shown_as_a_uid_not_disguised_as_a_name() -> None:
    """Ein stiller Rueckfall auf die UID liest sich im Bericht wie ein Titel.

    `ruleTitle` ist der Menschenname, `ruleUID` die Maschinen-ID — zwei
    verschiedene Dinge. Dieselbe Klasse wie das Alters-Etikett in #5185: die
    Zahl stimmte, das Etikett log.
    """
    ereignisse = decode_history(_hist(
        {"ruleUID": "lo-bridge-scrape-failed", "previous": "Normal", "current": "Pending"},
    ))
    assert ereignisse[0]["rule"] == "<ohne Titel, UID lo-bridge-scrape-failed>"
