"""Ein Urteil JE VERBINDUNG — und wie lange der Canary schon rot ist.

Warum es das gibt (Vorfall 2026-08-16 bis 2026-08-26, zehn Tage unbemerkt):

Der Canary fuhr drei Pruefungen als drei gewoehnliche Steps ohne
``continue-on-error``. Am 2026-08-25 (Lauf 32813924394) schlug die ERSTE fehl
(Versionsdrift der Tool-Pins) — und GitHub uebersprang daraufhin die beiden
folgenden. Gemessen an der Step-Liste jenes Laufs:

    failure  Check pinned schemas
    skipped  Audit environment and account separation
    skipped  Probe every read-only connection

Die toten Slack- und Notion-Verbindungen waren damit nicht "verdeckt", sondern
**nie gemessen worden**. Der Canary meldete taeglich rot und sagte nichts
darueber, was kaputt war; wer den Grund suchte, fand den Versionsdrift, behob
ihn nicht, und die eigentlichen Ausfaelle blieben unsichtbar.

Zwei Konsequenzen, beide hier umgesetzt:

1. **Jede Verbindung bekommt ihre eigene Zeile und ihre eigene Annotation.**
   Ein Sammel-Rot ("ok": false) zwingt zum Log-Lesen und laesst offen, ob eine
   oder alle vier Verbindungen tot sind.
2. **Das Alter wird angezeigt und eskaliert.** Ein Canary, der seit zehn Tagen
   rot ist, sieht in der Lauf-Liste genauso aus wie einer, der seit gestern rot
   ist — und wird deshalb genauso ignoriert. Ab ``_ESKALATION_TAGE`` Tagen
   sagt die Ausgabe das ausdruecklich.

Das Entkoppeln der Steps selbst passiert im Workflow (``composio-canary.yml``);
gepinnt in ``tests/test_composio_canary_per_connection.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ab hier ist "rot" kein Vorfall mehr, sondern ein Zustand — und Zustaende
# werden uebersehen. Drei Tage, weil ein Wochenende dazwischenliegen darf,
# ohne dass die Meldung sofort eskaliert.
_ESKALATION_TAGE = 3


def verdicts(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Ein Urteil je Verbindung, in stabiler Reihenfolge.

    ``skipped`` ist ausdruecklich NICHT ``ok``: eine Verbindung, die mangels
    Konfiguration nicht geprobt wurde, ist ungemessen. Sie als gruen zu
    fuehren waere genau die Luege, gegen die dieser Canary gebaut ist.
    """
    ergebnisse: list[dict[str, Any]] = []
    for probe in report.get("probes") or []:
        if probe.get("skipped"):
            urteil = "UNGEMESSEN"
        elif probe.get("ok"):
            urteil = "OK"
        else:
            urteil = "TOT"
        ergebnisse.append(
            {
                "toolkit": str(probe.get("toolkit", "?")),
                "tool": str(probe.get("tool", "?")),
                "urteil": urteil,
                "detail": str(probe.get("detail", "")),
            }
        )
    return ergebnisse


def annotations(urteile: list[dict[str, Any]], rot_seit_tagen: int | None) -> list[str]:
    """GitHub-Annotationen: je Verbindung eine, plus die Alterszeile.

    Eine Annotation pro Verbindung, damit die Lauf-Uebersicht ohne Log-Lesen
    sagt, WELCHE Verbindung tot ist — der Punkt, an dem die zehn Tage hingen.
    """
    zeilen: list[str] = []
    for u in urteile:
        if u["urteil"] == "TOT":
            zeilen.append(
                f"::error title=composio-canary::{u['toolkit']} TOT "
                f"({u['tool']}): {u['detail']}"
            )
        elif u["urteil"] == "UNGEMESSEN":
            zeilen.append(
                f"::warning title=composio-canary::{u['toolkit']} UNGEMESSEN "
                f"({u['tool']}) — nicht konfiguriert, also keine Aussage: {u['detail']}"
            )
    if rot_seit_tagen is not None and rot_seit_tagen >= _ESKALATION_TAGE and zeilen:
        zeilen.append(
            f"::error title=composio-canary::Der Canary ist seit {rot_seit_tagen} "
            "Tagen ohne gruenen Lauf. Dauerrot wird uebersehen — die Verbindungen "
            "oben sind seither ungeprueft bzw. tot."
        )
    return zeilen


def summary(urteile: list[dict[str, Any]], rot_seit_tagen: int | None) -> str:
    """Markdown fuer die Step-Summary — eine Zeile je Verbindung."""
    symbol = {"OK": "🟢", "TOT": "🔴", "UNGEMESSEN": "⚪"}
    kopf = "| Verbindung | Urteil | Detail |\n| --- | --- | --- |\n"
    reihen = "".join(
        f"| `{u['toolkit']}` | {symbol.get(u['urteil'], '?')} {u['urteil']} "
        f"| {u['detail'][:120]} |\n"
        for u in urteile
    )
    alter = ""
    if rot_seit_tagen is not None:
        alter = (
            f"\n**Letzter gruener Lauf: vor {rot_seit_tagen} Tag(en).**\n"
            if rot_seit_tagen > 0
            else "\n**Der letzte Lauf war gruen.**\n"
        )
    return f"### composio-canary\n\n{kopf}{reihen}{alter}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Urteil je Composio-Verbindung.")
    parser.add_argument("--report", required=True, help="composio_canary.json")
    parser.add_argument(
        "--red-since-days",
        type=int,
        default=None,
        help="Tage seit dem letzten gruenen Canary-Lauf; weglassen, wenn unbekannt.",
    )
    parser.add_argument("--summary-file", help="Datei fuer die Markdown-Summary.")
    args = parser.parse_args(argv)

    pfad = Path(args.report)
    try:
        report = json.loads(pfad.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Der Probe-Step lief nicht oder starb vor dem Schreiben. Das ist der
        # Zustand vom 2026-08-25 — und er darf NICHT als "nichts zu melden"
        # durchgehen, sonst ist dieser Bericht so blind wie sein Vorgaenger.
        print(
            "::error title=composio-canary::kein Probe-Bericht "
            f"({pfad}) — die Verbindungen wurden GAR NICHT geprueft."
        )
        return 1
    except json.JSONDecodeError as exc:
        print(f"::error title=composio-canary::Probe-Bericht unlesbar: {exc}")
        return 1

    urteile = verdicts(report)
    if not urteile:
        print("::error title=composio-canary::Bericht enthaelt keine einzige Probe.")
        return 1

    for zeile in annotations(urteile, args.red_since_days):
        print(zeile)

    text = summary(urteile, args.red_since_days)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)

    return 1 if any(u["urteil"] != "OK" for u in urteile) else 0


if __name__ == "__main__":
    sys.exit(main())
