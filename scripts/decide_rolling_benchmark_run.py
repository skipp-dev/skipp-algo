#!/usr/bin/env python3
"""Entscheidet, ob ein Fire des Rolling-Benchmarks wirklich laufen muss.

Der Workflow wird von ``workflow_run`` bei JEDEM erfolgreichen Producer-Lauf
ausgeloest. Der Producer hat neun Ticks je Werktag (08,10,12,14,16,18,20,21,22
UTC), der Benchmark feuerte damit bis zu neunmal — obwohl sein eigener
Kopfkommentar von zwei Laeufen ausgeht (Praemisse aus einer Zeit, als der
Producer 2x lief; gemessen 2026-08-29: acht Laeufe an einem Werktag,
366 Runner-Minuten).

Zwei Laeufe pro Werktag genuegen, aber es muessen die RICHTIGEN zwei sein:

* **Fenster A, 11:00-12:30 UTC** — bedient die drei Tages-Gates, die das
  datierte Artefakt ziehen (13:30, 14:00, 15:00 UTC). Die Obergrenze folgt
  der Konsumentenzeit, nicht einem Producer-Tick: ein ~46-Minuten-Lauf, der
  spaetestens 12:30 startet, ist vor 13:30 fertig. Die Untergrenze 11:00 ist
  eine Operator-Entscheidung (2026-08-29): frischere Daten, kleinerer Puffer.
* **Fenster B, ab 20:00 UTC** — der Benchmark scort ein 5-Tage-Ankerfenster,
  spaetere Laeufe sehen nachgereifte Labels. Genau deshalb dedupliziert der
  Accumulate-Schritt auf ``(family, anchor_ts)`` mit Tie-Break "laengste
  ``forward_closes``". Der erste Fire ab 20:00 traegt die reifsten Labels des
  Tages, ohne dass man wissen muesste, ob noch einer kommt.

**Im Zweifel wird gelaufen.** Kann der Aufrufer den heutigen Lauf-Zustand
nicht ermitteln (API-Fehler, fehlende Berechtigung), uebergibt er ``None`` —
und diese Funktion antwortet LAUFEN. Ein Gate, das bei Blindheit
ueberspringt, stoppt den Benchmark still und dauerhaft; ein ueberfluessiger
Lauf kostet 46 Minuten, ein stiller Stopp die Drift-Erkennung.

Nebenlaeufigkeit braucht hier keine eigene Sperre: der Workflow traegt
``concurrency: group: smc-measurement-benchmark-rolling`` auf oberster Ebene,
zwei fast gleichzeitige Fires laufen also nacheinander — der zweite sieht den
Erfolg des ersten und ueberspringt.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Fenster A: Untergrenze = Operator-Entscheidung (frischere Daten),
#: Obergrenze = Konsumentenzeit 13:30 minus ~46 min Laufzeit minus Puffer.
WINDOW_A_START_MIN: Final = 11 * 60
WINDOW_A_END_MIN: Final = 12 * 60 + 30
#: Fenster B: ab hier liegen die Producer-Ticks 20/21/22.
WINDOW_B_START_MIN: Final = 20 * 60


@dataclass(frozen=True)
class Decision:
    run: bool
    window: str
    reason: str


def _minutes(stamp: _dt.datetime) -> int:
    return stamp.hour * 60 + stamp.minute


def _parse(stamp: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(_dt.UTC)


def decide(
    *,
    now: _dt.datetime,
    event_name: str,
    producer_conclusion: str | None,
    todays_runs: list[dict] | None,
) -> Decision:
    """Entscheidet ueber EINEN Fire.

    ``todays_runs`` sind die heutigen Laeufe DIESES Workflows mit
    ``conclusion``, ``created_at`` und ``worked``; ``None`` heisst "konnte
    nicht gelesen werden" und fuehrt bewusst zu LAUFEN.

    Ein Fenster bedient nur ein Lauf, dessen WORKER gelaufen ist
    (``worked is True``). ``conclusion == "success"`` allein genuegt nicht:
    ein Fire, den dieses Gate uebersprungen hat, endet ebenfalls gruen (der
    Gate-Job war erfolgreich, der Worker ``skipped``). Bis 2026-10-01 zaehlte
    die Regel genau diese Laeufe mit — der uebersprungene 09:xx-Fire
    "bediente" Fenster A, und vor 20:00 UTC lief der Benchmark gar nicht mehr.
    Fehlt ``worked`` oder ist es ``None``, gilt der Lauf als nicht bedienend:
    Blindheit faellt auch auf dieser Achse auf LAUFEN.
    """
    if event_name == "workflow_dispatch":
        # Ein Mensch hat ausdruecklich danach gefragt. Das Gate steht nicht
        # zwischen Operator und Werkzeug.
        return Decision(True, "manual", "manueller Dispatch laeuft immer")

    if event_name == "workflow_run" and producer_conclusion != "success":
        return Decision(
            False, "none",
            f"Producer endete mit {producer_conclusion!r}, nicht 'success'",
        )

    if todays_runs is None:
        return Decision(
            True, "blind",
            "heutiger Lauf-Zustand nicht ermittelbar — im Zweifel laufen, "
            "sonst stoppt ein Gate-Fehler den Benchmark still",
        )

    successes = [
        r for r in todays_runs
        if r.get("conclusion") == "success" and r.get("worked") is True
    ]
    now_min = _minutes(now)

    if now_min >= WINDOW_B_START_MIN:
        served_b = [
            r for r in successes
            if _minutes(_parse(r["created_at"])) >= WINDOW_B_START_MIN
        ]
        if served_b:
            return Decision(False, "B", "Fenster B ist heute bereits bedient")
        return Decision(True, "B", "Fenster B: reifste Labels des Tages")

    if now_min < WINDOW_A_START_MIN:
        return Decision(
            False, "none",
            "vor Fenster A — ein Lauf hier waere bei der Abnahme um 13:30 "
            "aelter als noetig (Operator-Entscheidung 2026-08-29)",
        )

    if successes:
        return Decision(False, "A", "Fenster A ist heute bereits bedient")

    if now_min < WINDOW_A_END_MIN:
        return Decision(True, "A", "Fenster A: bedient die Tages-Gates ab 13:30")

    # Zwischen Fenster-A-Ende und 20:00, und der Tag hat noch keinen Erfolg:
    # besser spaet als gar nicht — die Historie braucht den Schnappschuss,
    # auch wenn die 13:30-Gates ihn nicht mehr sehen.
    return Decision(
        True, "net",
        "Sicherheitsnetz: Fenster A verstrichen, der Tag hat noch keinen "
        "erfolgreichen Lauf",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", default=None, help="ISO-Zeit (Default: jetzt UTC)")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--producer-conclusion", default=None)
    parser.add_argument(
        "--todays-runs", default=None,
        help='JSON-Liste [{"id":…,"conclusion":…,"created_at":…}]; fehlt/ungueltig ⇒ LAUFEN',
    )
    parser.add_argument(
        "--worked-run-ids", default=None,
        help="Run-Ids (durch Leerraum getrennt), deren Worker-Job mit success "
        "endete. Fehlt die Angabe, gilt KEIN Lauf als bedienend ⇒ LAUFEN.",
    )
    args = parser.parse_args(argv)

    now = _parse(args.now) if args.now else _dt.datetime.now(_dt.UTC)

    runs: list[dict] | None
    if args.todays_runs is None or not args.todays_runs.strip():
        runs = None
    else:
        try:
            parsed = json.loads(args.todays_runs)
            runs = parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            runs = None

    if runs is not None:
        # Der Worker-Befund kommt getrennt (eine Job-Abfrage je gruenem Lauf)
        # und wird hier an die Run-Liste gehaengt. Nicht lesbare Eintraege
        # fallen weg statt abzustuerzen — ein Lauf ohne Befund bedient nichts.
        worked_ids = {
            int(tok) for tok in (args.worked_run_ids or "").split() if tok.isdigit()
        }
        runs = [
            {**r, "worked": r.get("id") in worked_ids}
            for r in runs if isinstance(r, dict)
        ]

    decision = decide(
        now=now,
        event_name=args.event_name,
        producer_conclusion=args.producer_conclusion,
        todays_runs=runs,
    )

    print(f"[bench-gate] run={decision.run} window={decision.window}: {decision.reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        # `Path.open("a")` ist die im Repo sanktionierte Form fuer
        # $GITHUB_OUTPUT (vgl. scripts/hold_customer_surfaces.write_github_outputs);
        # das eingebaute open(...) faellt durch den Raw-Write-Waechter.
        # `reason` steht bewusst NUR im Log: es ist ein freier Satz, und ein
        # mehrzeiliger Wert braeuchte hier einen Heredoc mit
        # kollisionsfreiem Delimiter — Aufwand ohne Nutzen, den Workflow
        # liest nur `run` und `window`.
        with Path(out).open("a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if decision.run else 'false'}\n")
            fh.write(f"window={decision.window}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
