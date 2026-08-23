"""Entscheidet, ob ein Bindings-Snapshot einen Reparaturlauf ausloest.

Rein und ohne Netz, damit die Entscheidung einzeln beweisbar ist — die
Browser-Haelfte laesst sich nicht testen, die Entscheidung schon.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

#: Drei Fehlschlaege an denselben Zielen sind kein Flake, sondern ein Befund —
#: und ein vierter Lauf kostet einen Warteplatz in der Session-Gruppe, den ein
#: echter Save braucht.
DAILY_DISPATCH_CAP = 3


@dataclass(frozen=True)
class Decision:
    dispatch: bool
    reason: str


def decide(
    snapshot: dict,
    repair_dispatches_today: int,
    repair_in_flight: bool = False,
    dispatch_count_unknown: bool = False,
) -> Decision:
    """Entscheidet ueber EINEN Reparatur-Dispatch.

    ``repair_dispatches_today`` sind die Reparatur-Dispatches, die dieser
    Waechter heute (ET) selbst abgesetzt hat — nicht die workflow_dispatch-Laeufe
    des Save-Workflows. Der Unterschied ist nicht akademisch: an ET-2026-08-22
    waren 12 von 12 solcher Laeufe die eigenen Verify-Dispatches des Waechters
    und keiner davon eine Reparatur; die alte, breitere Zaehlung haette den
    Deckel jeden Tag ab der ersten Entscheidung gemeldet.

    ``dispatch_count_unknown`` sagt, dass der Aufrufer diese Zahl nicht
    ermitteln KONNTE. Ein unbekannter Deckel ist kein offener Deckel.
    """
    if not isinstance(snapshot, dict):
        # Fail closed: ein Top-Level-Snapshot, der kein Objekt ist (z.B. eine
        # JSON-Liste), ist syntaktisch gueltiges JSON, aber schema-fremd.
        return Decision(
            False,
            f"Snapshot ist kein Objekt ({type(snapshot).__name__}) — fail closed, kein Urteil",
        )

    mode = snapshot.get("executionMode")
    if mode != "verify-only":
        # Schleifenschutz: ein Reparatur-Snapshot traegt "repair-only" und darf
        # keinen weiteren ausloesen. Ein "write"-Lauf repariert ohnehin selbst.
        return Decision(False, f"executionMode={mode!r} — nur verify-only loest aus")

    bindings = snapshot.get("bindings")
    if not isinstance(bindings, dict):
        return Decision(False, "Snapshot ohne bindings — fail closed, kein Urteil")

    checked_consumers = bindings.get("checkedConsumers")
    if not isinstance(checked_consumers, int) or checked_consumers <= 0:
        # Leer ist nicht gruen (2026-08-14): ein Fehlschlag pusht bindings: [].
        # Ein Nicht-int-Wert (z.B. ein String "0") ist ebenso UNBEKANNT, nicht
        # "nicht leer" — sonst waere er in Python truthy und wuerde durchrutschen.
        return Decision(
            False,
            f"leere oder unklare Beobachtung (checkedConsumers={checked_consumers!r}) — kein Urteil",
        )

    consumers_raw = bindings.get("consumers")
    if consumers_raw is None:
        consumers_raw = []
    elif not isinstance(consumers_raw, list):
        return Decision(
            False,
            f"bindings.consumers ist keine Liste ({type(consumers_raw).__name__}) — "
            "fail closed, kein Urteil",
        )

    drifted = []
    for idx, consumer in enumerate(consumers_raw):
        if not isinstance(consumer, dict):
            # Schema-fremd: ein Konsument, der kein Objekt ist, laesst sich nicht
            # nach scriptName/mismatches befragen — fail closed statt zu werfen.
            return Decision(
                False,
                f"Konsument #{idx} ist kein Objekt ({type(consumer).__name__}) — "
                "fail closed, kein Urteil",
            )
        if consumer.get("mismatches"):
            drifted.append(consumer.get("scriptName"))

    if not drifted:
        return Decision(False, "keine Mismatches — nichts zu reparieren")

    if repair_in_flight:
        # Kein Stapeln: ein wartender Reparaturlauf reicht. Der Deckel allein
        # verhindert das nicht — drei Laeufe koennten sich sonst gleichzeitig um
        # denselben Warteplatz der Session-Gruppe draengen.
        return Decision(False, "ein Reparaturlauf ist bereits in flight — kein zweiter")

    if dispatch_count_unknown:
        # Ein Deckel, der nicht gezaehlt werden konnte, ist kein offener Deckel.
        # Der Aufrufer meldet das, wenn sein Listenfenster den ET-Tag nicht mehr
        # ueberdeckt — sonst waere ausgerechnet der lauteste Tag der, an dem der
        # Deckel aufgeht. Der Marker unten ist ein Vertrag mit dem Alarmschritt
        # in tv-post-mutation-verify.yml: ohne ihn waere dieser Ausgang der
        # stille Zwilling des erreichten Deckels.
        return Decision(
            False,
            "Listenfenster erschoepft — Zahl der heutigen Reparatur-Dispatches unbekannt, "
            f"fail closed, kein Dispatch; betroffen: {', '.join(str(d) for d in drifted)}",
        )

    if repair_dispatches_today >= DAILY_DISPATCH_CAP:
        # "Reparatur-Dispatches", nicht "Reparaturlaeufe": gezaehlt werden die
        # abgesetzten Dispatches dieses Waechters. Ob der bestellte Lauf dann
        # startete, sagt diese Zahl nicht — und darf sie nicht behaupten.
        return Decision(
            False,
            f"Deckel erreicht: {repair_dispatches_today}/{DAILY_DISPATCH_CAP} "
            "Reparatur-Dispatches heute — "
            f"Operator noetig, betroffen: {', '.join(str(d) for d in drifted)}",
        )

    return Decision(True, f"mismatch bei: {', '.join(str(d) for d in drifted)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument(
        "--repair-dispatches-today",
        type=int,
        default=0,
        help=(
            "Reparatur-Dispatches, die dieser Waechter heute (ET) selbst abgesetzt hat. "
            "NICHT die workflow_dispatch-Laeufe des Save-Workflows — die sind zum "
            "allergroessten Teil seine eigenen Verify-Dispatches."
        ),
    )
    parser.add_argument("--repair-in-flight", action="store_true")
    parser.add_argument(
        "--dispatch-count-unknown",
        action="store_true",
        help="Der Aufrufer konnte die Tageszahl nicht ermitteln — fail closed statt ungedeckelt.",
    )
    args = parser.parse_args()

    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except Exception as exc:  # jede Lesefehlerart faellt fail-closed
        decision = Decision(False, f"Snapshot unlesbar: {exc}")
    else:
        decision = decide(
            snapshot,
            args.repair_dispatches_today,
            args.repair_in_flight,
            args.dispatch_count_unknown,
        )

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"dispatch={'true' if decision.dispatch else 'false'}\n")
            handle.write(f"reason={decision.reason}\n")
    print(f"dispatch={decision.dispatch} reason={decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
