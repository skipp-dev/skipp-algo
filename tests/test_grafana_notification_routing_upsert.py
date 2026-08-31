"""Tests + guard rails for ``scripts/grafana_notification_routing_upsert.py``.

Keeps the Grafana *routing* (contact points + notification policy) reproducible
from the repo the same way ``test_grafana_alert_rules_upsert.py`` does for the
rules: fail CI if ``notification-routing.yaml`` becomes structurally invalid, if
the Slack contact point / severity route silently drifts, if a secret would be
committed instead of referenced via ``${...}``, or if the upsert
payload/endpoint regresses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "grafana_notification_routing_upsert.py"
ROUTING = REPO / "services" / "live_overlay_daemon" / "infra" / "grafana" / "notification-routing.yaml"
WORKFLOW = REPO / ".github" / "workflows" / "live-overlay-notification-routing-publish.yml"


def _load():
    spec = importlib.util.spec_from_file_location("grafana_notification_routing_upsert", SCRIPT)
    assert spec and spec.loader
    modu = importlib.util.module_from_spec(spec)
    sys.modules["grafana_notification_routing_upsert"] = modu
    spec.loader.exec_module(modu)
    return modu


mod = _load()


# --------------------------------------------------------------------------- #
# The committed routing file
# --------------------------------------------------------------------------- #
def test_repo_routing_is_structurally_valid() -> None:
    doc = mod.load_routing(ROUTING)
    assert mod.validate_routing(doc) == []


def test_repo_routing_pins_slack_contact_point_and_severity_route() -> None:
    """Drift guard: the intent (Slack + credential-covering severities) is pinned
    so a silent edit that drops the route or the contact point fails CI."""
    doc = mod.load_routing(ROUTING)
    cps = {c["name"]: c for c in doc["contactPoints"]}
    assert "slack-smc-alerts" in cps
    assert cps["slack-smc-alerts"]["type"] == "slack"

    policy = doc["policy"]
    assert policy["receiver"] == "slack-smc-alerts"  # catch-all root, nothing dropped
    # 2026-08-31: die generische Severity-Route ist entfernt (Wirkungs-Sweep E) --
    # sie setzte denselben Empfaenger wie die Wurzel und ueberschrieb kein
    # Zustellfeld, waehlte also 171 von 173 Regeln aus und aenderte nichts. Die
    # Deckung, die dieser Test schuetzen wollte, leistet seither die Wurzel
    # SELBST, und zwar vollstaendiger: sie faengt auch `info` und unbeschriftete
    # Regeln, die die Severity-Route gar nicht traf. Genau das wird jetzt
    # gepinnt -- ein Wechsel der Wurzel auf etwas anderes als das Auffangbecken
    # waere der Verlust, gegen den dieser Test steht.
    assert policy.get("group_by") == ["grafana_folder", "alertname"]


def test_repo_routing_commits_no_secret_only_a_placeholder() -> None:
    """The webhook must never be committed — only the ${SLACK_WEBHOOK_URL} ref."""
    text = ROUTING.read_text(encoding="utf-8")
    assert "hooks.slack.com" not in text
    assert "${SLACK_WEBHOOK_URL}" in text
    assert mod.find_placeholders(mod.load_routing(ROUTING)) == {"SLACK_WEBHOOK_URL"}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_flags_missing_contact_points() -> None:
    errs = mod.validate_routing({"policy": {"receiver": "x", "routes": []}})
    assert any("contactPoints" in e for e in errs)


def test_validate_flags_dangling_receiver() -> None:
    doc = {
        "contactPoints": [{"name": "slack", "type": "slack", "settings": {"url": "x"}}],
        "policy": {"receiver": "ghost", "routes": []},
    }
    errs = mod.validate_routing(doc)
    assert any("ghost" in e and "not a defined contact point" in e for e in errs)


def test_validate_flags_bad_matcher_operator() -> None:
    doc = {
        "contactPoints": [{"name": "s", "type": "slack", "settings": {"url": "x"}}],
        "policy": {
            "receiver": "s",
            "routes": [{"receiver": "s", "object_matchers": [["severity", "BADOP", "critical"]]}],
        },
    }
    errs = mod.validate_routing(doc)
    assert any("BADOP" in e for e in errs)


# --------------------------------------------------------------------------- #
# Placeholder resolution (secret injection at apply time)
# --------------------------------------------------------------------------- #
def test_resolve_placeholders_substitutes_from_env() -> None:
    out = mod.resolve_placeholders({"url": "${SLACK_WEBHOOK_URL}"}, {"SLACK_WEBHOOK_URL": "https://x"})
    assert out == {"url": "https://x"}


def test_resolve_placeholders_fails_loud_when_unset() -> None:
    with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL"):
        mod.resolve_placeholders({"url": "${SLACK_WEBHOOK_URL}"}, {})


# --------------------------------------------------------------------------- #
# Payload shapes
# --------------------------------------------------------------------------- #
def test_build_contact_point_body_shape() -> None:
    body = mod.build_contact_point_body(
        {"name": "slack-smc-alerts", "type": "slack", "settings": {"url": "https://x"}}
    )
    assert body == {
        "name": "slack-smc-alerts",
        "type": "slack",
        "settings": {"url": "https://x"},
        "disableResolveMessage": False,
    }


def test_build_policy_body_shape() -> None:
    body = mod.build_policy_body(
        {
            "receiver": "slack-smc-alerts",
            "group_by": ["grafana_folder", "alertname"],
            "routes": [
                {"receiver": "slack-smc-alerts", "object_matchers": [["severity", "=~", "critical|warning|high"]]}
            ],
        }
    )
    assert body["receiver"] == "slack-smc-alerts"
    assert body["group_by"] == ["grafana_folder", "alertname"]
    assert body["routes"][0]["object_matchers"] == [["severity", "=~", "critical|warning|high"]]
    assert body["routes"][0]["continue"] is False


# --------------------------------------------------------------------------- #
# HTTP layer (mocked)
# --------------------------------------------------------------------------- #
def test_upsert_contact_point_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        calls.append((method, path))
        if method == "GET":
            return []  # no existing contact points
        return None

    monkeypatch.setattr(mod, "_request", fake_request)
    action = mod.upsert_contact_point({"name": "slack-smc-alerts", "type": "slack", "settings": {"url": "x"}}, "k")
    assert action == "create"
    assert ("POST", "/api/v1/provisioning/contact-points") in calls


def test_upsert_contact_point_updates_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        calls.append((method, path))
        if method == "GET":
            return [{"name": "slack-smc-alerts", "uid": "abc123"}]
        return None

    monkeypatch.setattr(mod, "_request", fake_request)
    action = mod.upsert_contact_point({"name": "slack-smc-alerts", "type": "slack", "settings": {"url": "x"}}, "k")
    assert action == "update"
    assert ("PUT", "/api/v1/provisioning/contact-points/abc123") in calls


def test_put_policy_hits_policies_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT wie bisher — und seit 2026-08-30 ein GET hinterher.

    Die Ruecklese gehoert zum Vertrag: ohne sie kann der Upsert nicht sehen,
    dass die Instanz etwas anderes bekommen hat als die Datei sagt.
    """
    aufrufe: list[dict[str, Any]] = []
    body = {"receiver": "slack-smc-alerts"}

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        aufrufe.append({"method": method, "path": path, "payload": payload, "headers": extra_headers})
        return body if method == "GET" else None

    monkeypatch.setattr(mod, "_request", fake_request)
    mod.put_policy(body, "k")
    assert [a["method"] for a in aufrufe] == ["PUT", "GET"], (
        f"erwartet PUT gefolgt von der Ruecklese; war: {[a['method'] for a in aufrufe]}"
    )
    assert aufrufe[0]["path"] == "/api/v1/provisioning/policies"
    assert aufrufe[0]["headers"] == {"X-Disable-Provenance": "true"}


def test_put_policy_raises_when_the_instance_got_something_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der reale Fall vom 2026-08-30: Route da, Felder verschluckt.

    Vorher meldete der Upsert Erfolg, weil er alles getan hatte, was er kannte.
    """
    gesendet = {"receiver": "root", "routes": [{
        "receiver": "laut", "object_matchers": [["required_check", "=", "true"]],
        "group_by": ["alertname"], "repeat_interval": "30m",
    }]}
    verschluckt = {"receiver": "root", "routes": [{
        "receiver": "laut", "object_matchers": [["required_check", "=", "true"]],
    }]}

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        return verschluckt if method == "GET" else None

    monkeypatch.setattr(mod, "_request", fake_request)
    with pytest.raises(RuntimeError, match="deklariert ist nicht ausgeliefert"):
        mod.put_policy(gesendet, "k")


# --------------------------------------------------------------------------- #
# Deploy workflow wiring
# --------------------------------------------------------------------------- #
def test_workflow_deploys_routing_with_secret() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/grafana_notification_routing_upsert.py" in text
    # Secret plumbing: the webhook comes from a GitHub secret, the token reuses
    # the existing GRAFANA_API_TOKEN mapped to GRAFANA_API_KEY.
    assert "SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}" in text
    assert "GRAFANA_API_KEY: ${{ secrets.GRAFANA_API_TOKEN }}" in text
    # Push trigger must watch the routing file so a change actually deploys.
    assert "services/live_overlay_daemon/infra/grafana/notification-routing.yaml" in text
    # Dry-run preflight (validates without the secret) must run.
    assert "--dry-run" in text


def test_required_check_route_precedes_the_generic_severity_route() -> None:
    """Reihenfolge ist hier die ganze Wirkung.

    Beide Routen haben `continue: false`. Steht die generische Severity-Route
    zuerst, faengt sie jede `critical`-Meldung ab — und die required-Check-Route
    darunter wird nie erreicht. Der Unterschied waere dann still weg: dieselbe
    Gruppierung, dasselbe Wiederholintervall, dieselbe Unauffindbarkeit, gegen
    die sie 2026-08-29 gebaut wurde.
    """
    import yaml

    routing = yaml.safe_load(
        (REPO / "services/live_overlay_daemon/infra/grafana/notification-routing.yaml")
        .read_text(encoding="utf-8")
    )
    routes = routing["policy"]["routes"]
    idx_required = next(
        (i for i, r in enumerate(routes)
         if any(m[0] == "required_check" for m in r.get("object_matchers", []))),
        None,
    )
    assert idx_required is not None, "die required-Check-Route ist verschwunden"
    # 2026-08-31: frueher verglich dieser Test die Position gegen die generische
    # Severity-Route. Die ist entfernt (Wirkungs-Sweep E) -- und ein Test, der an
    # EINER konkreten Nachbarroute haengt, stirbt mit ihr, obwohl der Mechanismus
    # weiterlebt. Gepinnt wird deshalb die Invariante selbst: KEINE terminierende
    # Route darf vor der required-Check-Route stehen, egal welche.
    verschluckt = [
        (i, r.get("object_matchers"))
        for i, r in enumerate(routes[:idx_required])
        if not r.get("continue", False)
    ]
    assert not verschluckt, (
        f"terminierende Route(n) VOR der required-Check-Route (Position "
        f"{idx_required}): {verschluckt} — sie fangen die Meldung ab, und die "
        "eigene Behandlung ist wirkungslos"
    )
    r = routes[idx_required]
    assert r.get("group_by") == ["alertname"], (
        "ohne eigenes group_by wird der required-Alarm mit den Ordner-Geschwistern "
        f"eingesammelt; ist: {r.get('group_by')}"
    )
    assert r.get("repeat_interval") == "30m", (
        "ohne kuerzeres repeat_interval piept es einmal und schweigt 4 h "
        f"(Grafana-Vorgabe); ist: {r.get('repeat_interval')}"
    )


def test_the_required_check_rule_carries_the_label_the_route_matches() -> None:
    """Route ohne Label ist Dekoration — und Label ohne Route auch.

    Die beiden Dateien sind getrennt deploybar; nur diese Zeile haelt sie
    zusammen.
    """
    import yaml

    rules = yaml.safe_load(
        (REPO / "services/live_overlay_daemon/infra/grafana/alert-rules.yaml")
        .read_text(encoding="utf-8")
    )
    treffer = [
        r for g in rules.get("groups", []) for r in g.get("rules", [])
        if (r.get("labels") or {}).get("required_check") == "true"
    ]
    assert treffer, "keine Regel traegt `required_check: true` — die Route laeuft ins Leere"
    for r in treffer:
        assert (r.get("labels") or {}).get("severity") == "critical", (
            f"{r.get('title')!r} traegt required_check, aber severity="
            f"{(r.get('labels') or {}).get('severity')!r} — dann ist es wieder eine "
            "Warnung unter hunderten"
        )
        assert r.get("for") == "15m", (
            f"{r.get('title')!r} hat for={r.get('for')!r}. Gemessen 2026-08-29: "
            "Flatterer 1-5 min, echter Vorfall 47 min. Wer das aendert, aendert die "
            "Trennlinie zwischen beidem — mit Messung, nicht mit Gefuehl."
        )


def test_route_level_fields_are_passed_through_not_silently_dropped() -> None:
    """Der Defekt vom 2026-08-30: vier Felder fielen still unter den Tisch.

    `build_policy_body` baute jede Route aus genau drei Feldern. `group_by`,
    `group_wait`, `group_interval` und `repeat_interval` standen in der YAML,
    wurden von Tests gepinnt — und kamen bei Grafana nie an. Aufgefallen ist es
    erst beim Nachlesen des LIVE-Zustands: Route da, Matcher richtig,
    `group_by=None repeat=None`.
    """
    body = mod.build_policy_body({
        "receiver": "root",
        "routes": [{
            "receiver": "laut",
            "object_matchers": [["required_check", "=", "true"]],
            "group_by": ["alertname"],
            "group_wait": "30s",
            "repeat_interval": "30m",
            "continue": False,
        }],
    })
    r = body["routes"][0]
    assert r["group_by"] == ["alertname"], "group_by faellt wieder unter den Tisch"
    assert r["group_wait"] == "30s"
    assert r["repeat_interval"] == "30m"


def test_absent_route_fields_are_omitted_rather_than_sent_as_null() -> None:
    """Nicht gesetzt heisst weglassen — ein `null` waere eine Aussage."""
    body = mod.build_policy_body({
        "receiver": "root",
        "routes": [{"receiver": "x", "object_matchers": [["severity", "=", "critical"]]}],
    })
    r = body["routes"][0]
    for feld in ("group_by", "group_wait", "group_interval", "repeat_interval"):
        assert feld not in r, f"{feld} wurde als None mitgeschickt"


def test_readback_drift_is_detected_field_by_field() -> None:
    """Die Ruecklese ist der einzige Ort, an dem 'deklariert != ausgeliefert' auffaellt.

    Ein Upsert, der nur sendet, kann die Klasse strukturell nicht sehen — er hat
    ja alles getan, was er kennt.
    """
    gesendet = {"receiver": "root", "routes": [{
        "receiver": "laut", "object_matchers": [["required_check", "=", "true"]],
        "group_by": ["alertname"], "repeat_interval": "30m",
    }]}
    # genau der reale Fall: Route da, Felder verschluckt
    verschluckt = {"receiver": "root", "routes": [{
        "receiver": "laut", "object_matchers": [["required_check", "=", "true"]],
    }]}
    drift = mod.policy_drift(gesendet, verschluckt)
    assert any("group_by" in d for d in drift), drift
    assert any("repeat_interval" in d for d in drift), drift


def test_readback_without_drift_is_quiet() -> None:
    """Gegenprobe — sonst waere die Erkennung nur ein Dauer-Alarm."""
    body = {"receiver": "root", "routes": [{
        "receiver": "laut", "object_matchers": [["required_check", "=", "true"]],
        "group_by": ["alertname"], "repeat_interval": "30m",
    }]}
    assert mod.policy_drift(body, body) == []


def test_a_reordered_readback_is_drift_because_order_decides() -> None:
    """`continue: false` laesst die ERSTE passende Route gewinnen.

    Kommt die Reihenfolge anders an, ist die eigene Behandlung wirkungslos —
    und zwar still.
    """
    a = {"routes": [{"receiver": "laut", "object_matchers": [["required_check", "=", "true"]]},
                    {"receiver": "leise", "object_matchers": [["severity", "=~", "critical"]]}]}
    b = {"routes": [{"receiver": "leise", "object_matchers": [["severity", "=~", "critical"]]},
                    {"receiver": "laut", "object_matchers": [["required_check", "=", "true"]]}]}
    assert mod.policy_drift(a, b) != []


def test_a_dropped_route_is_drift_even_when_the_survivors_match() -> None:
    """Eine ganz verschluckte Route faellt nur ueber die ANZAHL auf.

    Der Feld-fuer-Feld-Vergleich laeuft paarweise; fehlt eine Route, verschiebt
    sich die Zuordnung oder endet frueh, und die uebrigen sehen korrekt aus.
    Diese Luecke ist am 2026-08-30 durch eine Mutationsprobe aufgefallen: der
    Zaehl-Vergleich liess sich abschalten, ohne dass ein Test rot wurde — die
    einzige gruen gebliebene Probe des Tages, die ein echtes Loch zeigte statt
    einer wirkungslosen Mutation.
    """
    gesendet = {"routes": [
        {"receiver": "laut", "object_matchers": [["required_check", "=", "true"]]},
        {"receiver": "leise", "object_matchers": [["severity", "=~", "critical"]]},
    ]}
    eine_weg = {"routes": [
        {"receiver": "laut", "object_matchers": [["required_check", "=", "true"]]},
    ]}
    drift = mod.policy_drift(gesendet, eine_weg)
    assert drift, "eine verschluckte Route blieb unbemerkt"
    assert any("Routenzahl" in d for d in drift), drift


def test_an_added_route_is_drift_too() -> None:
    """Gegenrichtung: die Instanz traegt mehr, als gesendet wurde.

    Etwa ein Rest aus der UI, den der PUT haette ersetzen sollen — der Baum
    wird als GANZES gesetzt, alles andere ist Drift.
    """
    gesendet = {"routes": [{"receiver": "laut", "object_matchers": [["a", "=", "b"]]}]}
    plus_eine = {"routes": [
        {"receiver": "laut", "object_matchers": [["a", "=", "b"]]},
        {"receiver": "fremd", "object_matchers": [["x", "=", "y"]]},
    ]}
    assert any("Routenzahl" in d for d in mod.policy_drift(gesendet, plus_eine))


def test_a_successful_readback_says_so(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Sonst ist 'Ruecklese fand statt' von 'Ruecklese wegoptimiert' nicht zu trennen.

    Die Zeile ist zugleich die Versionsprobe des Beweis-Eintrags: erscheint sie,
    lief der Code MIT Ruecklese.
    """
    body = {"receiver": "root", "routes": [
        {"receiver": "laut", "object_matchers": [["required_check", "=", "true"]]},
    ]}
    monkeypatch.setattr(
        mod, "_request",
        lambda method, path, key, payload=None, extra_headers=None: body if method == "GET" else None,
    )
    mod.put_policy(body, "k")
    assert "policy-readback: 1 Route(n) unveraendert angekommen" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# 2026-08-31, Wirkungs-Sweep Befund E: eine Route, die nichts aendert
# --------------------------------------------------------------------------- #
#: Felder, ueber die eine Route ihre Wirkung ausuebt. Alles andere (Matcher,
#: Kommentare) entscheidet nur, WEN sie faengt -- nicht, was danach anders ist.
_ZUSTELLFELDER = (
    "receiver",
    "group_by",
    "group_wait",
    "group_interval",
    "repeat_interval",
    "mute_time_intervals",
    "active_time_intervals",
)


def _routen_mit_eltern(knoten: dict, geerbt: dict) -> list[tuple[dict, dict]]:
    """Jede Route zusammen mit dem Zustand, den sie ohne eigene Angabe erbt."""
    raus: list[tuple[dict, dict]] = []
    effektiv = {feld: knoten.get(feld) for feld in _ZUSTELLFELDER}
    for route in knoten.get("routes") or []:
        raus.append((route, effektiv))
        kind_geerbt = {
            feld: (route[feld] if feld in route else effektiv[feld])
            for feld in _ZUSTELLFELDER
        }
        raus.extend(_routen_mit_eltern(route, kind_geerbt))
    return raus


def test_no_route_selects_without_changing_anything() -> None:
    """Eine Route, die dasselbe tut wie ihr Elternteil, ist Dekoration.

    Gemessen 2026-08-31 an der Live-Policy: die generische Severity-Route setzte
    denselben Empfaenger wie die Wurzel und ueberschrieb kein einziges
    Zustellfeld. Sie waehlte 171 von 173 Regeln aus und behandelte sie exakt so,
    wie die Wurzel sie ohnehin behandelt -- der Baum sah nach
    Severity-Behandlung aus, ohne eine zu haben.

    Routen MIT Kindern sind ausgenommen: dort ist die Gruppierung selbst der
    Zweck, und die Wirkung steckt in den Kindern. Ohne diese Ausnahme haette der
    Waechter einen voellig korrekten Zustand angeklagt.
    """
    import yaml

    routing = yaml.safe_load(
        (REPO / "services/live_overlay_daemon/infra/grafana/notification-routing.yaml")
        .read_text(encoding="utf-8")
    )
    paare = _routen_mit_eltern(routing["policy"], {})
    assert paare, "keine Route gefunden — die Ableitung ist blind, der Test waere vakuum"

    vakuum = []
    for route, geerbt in paare:
        if route.get("routes"):
            continue  # Sammelknoten: die Wirkung liegt in den Kindern
        unterschiede = [
            feld
            for feld in _ZUSTELLFELDER
            if feld in route and route[feld] != geerbt.get(feld)
        ]
        if not unterschiede:
            vakuum.append(route.get("object_matchers"))
    assert not vakuum, (
        "Route(n) ohne Wirkung — sie selektieren, aendern aber kein Zustellfeld "
        f"gegenueber dem Elternteil: {vakuum}. Entweder ein abweichendes Ziel/"
        "Timing geben oder die Route weglassen; die Wurzel faengt ohnehin alles."
    )
