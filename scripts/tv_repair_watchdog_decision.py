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


def decide(snapshot: dict, dispatches_today: int, repair_in_flight: bool = False) -> Decision:
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

    if dispatches_today >= DAILY_DISPATCH_CAP:
        return Decision(
            False,
            f"Deckel erreicht: {dispatches_today}/{DAILY_DISPATCH_CAP} Reparaturlaeufe heute — "
            f"Operator noetig, betroffen: {', '.join(str(d) for d in drifted)}",
        )

    return Decision(True, f"mismatch bei: {', '.join(str(d) for d in drifted)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--dispatches-today", type=int, default=0)
    parser.add_argument("--repair-in-flight", action="store_true")
    args = parser.parse_args()

    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except Exception as exc:  # jede Lesefehlerart faellt fail-closed
        decision = Decision(False, f"Snapshot unlesbar: {exc}")
    else:
        decision = decide(snapshot, args.dispatches_today, args.repair_in_flight)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"dispatch={'true' if decision.dispatch else 'false'}\n")
            handle.write(f"reason={decision.reason}\n")
    print(f"dispatch={decision.dispatch} reason={decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
