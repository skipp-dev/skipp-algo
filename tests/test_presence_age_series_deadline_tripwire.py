"""Stolperdraht: die Praesenz-Sonde ist erst zur HAELFTE geliefert.

#5218 hat die Praesenz je Workflow einzeln ermittelbar gemacht -- die
Voraussetzung dafuer, dass ``GITHUB_WORKFLOW_MONITOR_EXPECTED`` ueberhaupt
gesetzt werden kann, ohne taeglichen Fehlalarm zu erzeugen (die geteilte
Lauf-Seite deckte gemessen neun Stunden ab; ein Daily fehlte darauf zwei
Drittel des Tages, und die Regel laeuft mit ``for: 6h``).

Was NOCH FEHLT und ohne diesen Test nur in Prosa stuende:

1. Die Reihe ``live_overlay_github_workflow_expected_age_seconds`` -- das Alter
   des neuesten Laufs je deklariertem Workflow. Erst sie macht "gestoppt" als
   steigenden WERT alarmierbar statt als fehlende Reihe. Sie war in #5218
   gebaut und wurde wieder ENTFERNT, weil
   ``test_no_emitted_monitoring_metric_is_unconsumed`` sie zu Recht als
   unkonsumiert anklagte: keine Regel, kein Panel las sie.
2. Die Alarmregel darauf, mit einem Schwellwert oberhalb der legitimen
   Fr->Mo-Luecke (gemessen 71,5-72 h ueber die vereinigte Cron-Feuerungsliste;
   ``meta-watchdog`` rechnet fuer denselben Fall mit 80 h).

Beides gehoert in EINEN Commit -- getrennt ist das eine unkonsumiert und das
andere ohne Datenbasis.

WARUM DIESER TEST EXISTIERT. Die Reihenfolge "erst deployen, dann die Reihe
live sehen, dann die Regel darauf richten" ist richtig, aber sie ist ein
Zukunfts-Versprechen: nichts liest sie zum passenden Zeitpunkt erneut. Dieses
Repo hat dafuer eine ausdrueckliche Regel (CLAUDE.md, "Forward promises need a
mechanism") und diesen Test als Vorlage. Er ist der Mechanismus.

ER ZIEHT SICH SELBST ZURUECK: sobald Reihe UND Konsument beide da sind, ist die
Zusicherung erfuellt und die Datei kann geloescht werden -- so wie
``test_pine_const_getter_migration_tripwire.py`` sich mit #5105 selbst erledigt
hat.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_METRICS = REPO / "services" / "live_overlay_daemon" / "metrics.py"
_RULES = REPO / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"

#: Die Reihe, um die es geht.
_SERIES = "live_overlay_github_workflow_expected_age_seconds"

#: Frist. Gewaehlt als eine volle Arbeitswoche nach #5218: der Daemon muss
#: deployt sein, die Reihe live gesehen, die Regel gesetzt. Verlaengern heisst
#: Datum UND Begruendung hier erneuern -- ein stilles Hochsetzen ist genau der
#: Dauer-Mute, gegen den dieses Repo seine Ausnahmen datiert.
_FRIST = dt.date(2026, 9, 7)


def _emitted() -> bool:
    return _SERIES in _METRICS.read_text(encoding="utf-8")


def _consumed() -> bool:
    return _SERIES in _RULES.read_text(encoding="utf-8")


def test_the_age_series_and_its_alert_rule_land_together() -> None:
    """Nie das eine ohne das andere -- in BEIDE Richtungen.

    Eine emittierte Reihe ohne Konsument ist ein unsichtbares Signal (dafuer
    gibt es bereits einen eigenen Waechter). Eine Regel ohne Reihe ist eine
    Zusicherung ohne Datenbasis, und sie ist die gefaehrlichere Haelfte: unter
    ``noDataState: OK`` sieht ihre Stille aus wie Gesundheit -- exakt der
    Zustand, den dieser ganze Umbau beseitigen soll.
    """
    emitted, consumed = _emitted(), _consumed()
    assert emitted == consumed, (
        f"{_SERIES}: emittiert={emitted}, von einer Alarmregel gelesen={consumed}. "
        "Beides gehoert in denselben Commit."
    )


def test_the_presence_age_work_is_finished_before_its_deadline() -> None:
    """Nach der Frist wird die halbfertige Sonde rot, statt still liegenzubleiben.

    Bewusst OHNE ``pytest.skip``: solange die Frist laeuft, ist die Zusicherung
    schlicht ERFUELLT -- das ist ein gueltiges Ergebnis, kein Grund, den Lauf
    auszulassen. Ein uebersprungener Test ist einer, der nicht laeuft, und
    dieses Repo fuehrt darueber zu Recht ein Budget.
    """
    if _emitted() and _consumed():
        return  # erfuellt -- diese Datei darf geloescht werden
    heute = dt.datetime.now(dt.UTC).date()
    if heute <= _FRIST:
        return  # Frist laeuft noch: die Zusicherung ist (noch) erfuellt
    raise AssertionError(
        f"Frist {_FRIST.isoformat()} verstrichen (heute {heute.isoformat()}): "
        f"{_SERIES} fehlt weiterhin als Reihe und/oder als Alarmregel.\n"
        "Damit ist die Praesenz-Ueberwachung weiter nur zur Haelfte gebaut -- "
        "die Sonde ermittelt je Workflow korrekt, aber 'laeuft seit N Stunden "
        "nicht mehr' ist noch nicht alarmierbar.\n"
        "Entweder fertigstellen (Reihe in metrics.py + Regel in alert-rules.yaml, "
        "Schwellwert oberhalb der Fr->Mo-Luecke von 72 h; meta-watchdog nimmt 80 h) "
        "oder die Frist hier mit NEUER Begruendung verschieben."
    )
