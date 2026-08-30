"""Draht A: der Ablauf-Empfaenger — und warum er nichts ausliefert.

Recherche 2026-08-30: eine Vorwarnung vor dem Token-Ablauf gibt es nicht;
``composio.connected_account.expired`` feuert erst NACH dem gescheiterten
Refresh und hat weder Zustell-SLA noch Retry noch Dead-Letter. Der Draht ist
deshalb das schnelle, aber unzuverlaessige Signal — der taegliche Poll bleibt
der fail-closed-Boden darunter.

Der Kern dieser Datei ist die ZIRKULARITAET: der naheliegende Alarmweg
(Slack-DM oder GitHub-Issue wie im Grafana-Fanout nebenan) laeuft durch
``composio_ops`` — also durch genau die Schicht, deren Ausfall gemeldet werden
soll. Stirbt Slack, stirbt die Slack-Meldung mit. Deshalb liefert dieser
Empfaenger nichts aus, sondern haelt den Befund fuer die ``/metrics``-Flaeche,
die Prometheus HOLT.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services.live_overlay_daemon import composio_lifecycle_receiver as receiver

_EVENT = {
    "id": "evt_1",
    "type": "composio.connected_account.expired",
    "timestamp": "2026-08-30T03:12:00Z",
    "data": {
        "connected_account_id": "ca_6IzMhvyi5eZX",
        "toolkit_slug": "SLACK",
        "user_id": "597960a4-5dff-4463-b48b-b1dd0d29012d",
    },
}


@pytest.fixture(autouse=True)
def _sauber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COMPOSIO_LIFECYCLE_LEDGER", str(tmp_path / "lifecycle.jsonl"))
    receiver.reset_state()
    yield
    receiver.reset_state()


def test_an_expiry_event_is_recorded_and_visible_to_metrics() -> None:
    """Der Befund muss die Gauge erreichen — sonst ist der Draht folgenlos."""
    ergebnis = receiver.record(_EVENT)
    assert ergebnis["recorded"] is True
    assert ergebnis["toolkit"] == "slack"
    sichtbar = receiver.expired_connections()
    assert list(sichtbar) == ["ca_6IzMhvyi5eZX"]
    assert sichtbar["ca_6IzMhvyi5eZX"]["user_id"].startswith("597960a4")


def test_the_finding_survives_in_the_ledger(tmp_path: Path) -> None:
    """Der Prozesszustand stirbt mit dem Neustart, das Ledger nicht."""
    receiver.record(_EVENT)
    zeilen = (tmp_path / "lifecycle.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(zeilen) == 1
    eintrag = json.loads(zeilen[0])
    assert eintrag["toolkit"] == "slack" and eintrag["account_id"] == "ca_6IzMhvyi5eZX"


def test_an_unwritable_ledger_does_not_swallow_the_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Das Ledger ist die Nachlese, nicht der Alarm.

    Ein nicht schreibbarer Pfad darf den Befund nicht verschlucken — sonst
    haengt der einzige schnelle Draht an einer Plattenschreibung.
    """
    monkeypatch.setenv("COMPOSIO_LIFECYCLE_LEDGER", "/proc/gibt-es-nicht/x.jsonl")
    ergebnis = receiver.record(_EVENT)
    assert ergebnis["recorded"] is True
    assert receiver.expired_connections(), "der Prozesszustand muss den Befund halten"


def test_a_foreign_event_is_acknowledged_but_not_recorded() -> None:
    """200 statt Fehlercode: ein Fehler brächte Composio nur zum Wiederholen."""
    ergebnis = receiver.record({"id": "e", "type": "composio.trigger.message", "data": {}})
    assert ergebnis["ok"] is True and ergebnis["recorded"] is False
    assert not receiver.expired_connections()


def test_a_payload_without_ids_still_records_something() -> None:
    """Lieber ein Befund mit 'unbekannt' als ein stiller Verlust."""
    ergebnis = receiver.record({"type": receiver._EXPIRY_EVENT, "data": {}})
    assert ergebnis["recorded"] is True
    assert list(receiver.expired_connections()) == ["unbekannt"]


def test_the_receiver_delivers_nothing_through_composio() -> None:
    """DER Kernpunkt: der Alarm darf nicht durch das Ausgefallene laufen.

    Ein Slack-DM oder GitHub-Issue via ``composio_ops`` — das Muster des
    Grafana-Fanouts nebenan — waere zirkulaer: stirbt die Slack-Verbindung,
    stirbt die Meldung mit ihr. Dieser Pin macht den Rueckfall in dieses
    naheliegende Muster rot.
    """
    # Ueber den AST, nicht ueber den Text: der erste Entwurf dieses Tests
    # griff per Substring und schlug an der eigenen Doku an, die
    # ``composio_ops`` erklaerend nennt. Ein Waechter, der Prosa fuer Code
    # haelt, klagt korrekte Zustaende an — die Falle, gegen die dieses Repo
    # eine eigene Notiz fuehrt.
    baum = ast.parse(Path(receiver.__file__).read_text(encoding="utf-8"))

    importiert: set[str] = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            importiert.update(alias.name.split(".")[0] for alias in knoten.names)
        elif isinstance(knoten, ast.ImportFrom):
            if knoten.module:
                importiert.add(knoten.module.split(".")[0])
            importiert.update(alias.name for alias in knoten.names)
    assert "composio_ops" not in importiert, (
        "der Empfaenger importiert composio_ops — damit laeuft der Alarm ueber "
        f"die Schicht, deren Ausfall er meldet (Importe: {sorted(importiert)})"
    )

    gerufen = {
        knoten.func.attr
        for knoten in ast.walk(baum)
        if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute)
    }
    for verbot in ("notify_slack", "send_slack_dm", "send_slack_channel_message",
                   "create_github_issue", "comment_github_issue", "execute_tool"):
        assert verbot not in gerufen, f"{verbot}() macht den Alarm zirkulaer"


def test_the_metrics_surface_exposes_the_count() -> None:
    """Ohne Gauge ist der Befund nur ein Logeintrag, den niemand liest."""
    quelle = (
        Path(receiver.__file__).resolve().parent / "metrics.py"
    ).read_text(encoding="utf-8")
    assert "composio_lifecycle_receiver.expired_connections()" in quelle, (
        "metrics.py liest den Befundstand nicht — die Gauge waere konstant"
    )
    assert "live_overlay_composio_expired_connections" in quelle


def test_the_receiver_is_mounted_independently_of_chatops() -> None:
    """Der ChatOps-Import zieht composio_ops nach.

    Haenge dieser Empfaenger an dessen try-Block, riss ein Fehlschlag DORT
    ihn stumm mit — genau die Kopplung, gegen die er gebaut ist.
    """
    quelle = (
        Path(receiver.__file__).resolve().parent / "main.py"
    ).read_text(encoding="utf-8")
    block = quelle[quelle.index("from . import composio_lifecycle_receiver") - 400 :]
    assert "app.include_router(composio_lifecycle_receiver.router)" in block
    kopf = quelle[: quelle.index("from . import composio_lifecycle_receiver")]
    assert kopf.rstrip().endswith("try:"), (
        "der Empfaenger haengt nicht in einem EIGENEN try-Block"
    )


def test_the_expiry_event_is_pinned_to_webhook_version_v3() -> None:
    """Gemessen am 2026-08-30 gegen den Projekt-Key: das Ereignis gibt es NUR in V3.

    Ein Abonnement in V1/V2 bekaeme es nie zu sehen — und der Draht waere
    still tot, ohne dass irgendetwas rot wuerde.
    """
    assert receiver._REQUIRED_WEBHOOK_VERSION == "V3"
