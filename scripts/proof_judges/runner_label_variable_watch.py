#!/usr/bin/env python3
"""Urteiler ueber den Job-Log des Runner-Variablen-Waechters (#5178).

Was hier bewiesen werden soll, ist eng und pruefbar: die Sonde hat wirklich
gemessen -- also die variablengesteuerten ``runs-on``-Variablen aus den
Workflows ABGELEITET und fuer jede ein Urteil gerendert -- statt bloss zu
starten und still gruen zu enden.

Der Unterschied ist der ganze Punkt der Aenderung. Ein Waechter, dessen
Ableitung leer laeuft, urteilt ueber eine leere Menge und meldet Erfolg; das
sieht im Run-Status exakt aus wie ein gesunder Lauf. Genau diese Klasse
(``skipp-empty-result-is-not-a-finding``) hat dieses Repo mehrfach bezahlt,
zuletzt bei den Wachposten, deren Population aus sich selbst stammte.

Evidenz ist der Job-Log (``{"log": ...}``), weil die Sonde ihren Bericht nach
stdout schreibt und der Aufrufer ihn mit ``tee -a "$GITHUB_STEP_SUMMARY"``
weiterreicht -- absichtlich kein eigener Schreibpfad, damit es nicht zwei
Wahrheiten ueber denselben Bericht gibt.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.proof_judges import Verdict

#: Die Kopfzeile der Bericht-Tabelle. Sie existiert erst seit #5178 und ist
#: damit zugleich die Versionsprobe: erscheint sie, lief der neue Code.
_TABLE_HEADER = "| Variable | Wert | Lanes | Urteil |"

#: "Geprueft: N variablengesteuerte `runs-on`-Variablen ueber M Workflow-Dateien."
_SCOPE_RE = re.compile(
    r"Geprueft:\s*(?P<vars>\d+)\s+variablengesteuerte .*?ueber\s+(?P<files>\d+)\s+Workflow-Dateien"
)

#: Eine Urteilszeile: | `NAME` | `WERT` | N | URTEIL |
#:
#: BEWUSST NICHT auf ``^`` verankert, und das ist der Kern der Sache: die
#: Evidenz ist ein GitHub-Job-Log, und dort traegt jede Zeile ein Praefix aus
#: Job-Name, Step-Name und Zeitstempel (``watch\tArm-Runner...\t2026-...Z ``).
#: Die erste Fassung dieses Urteilers (#5178) war verankert und fand deshalb
#: NULL Urteilszeilen im echten Lauf 33240542676 — sie haette jeden gesunden
#: Lauf als ``rows_missing`` angeklagt, waehrend Kopfzeile und Umfangszeile
#: (unverankert gesucht) sauber matchten. Gemessen, nicht vermutet: der Korpus
#: unter tests/proof_corpus/ ist genau dieser Lauf.
_ROW_RE = re.compile(
    r"\|\s*`(?P<name>[A-Z][A-Z0-9_]*)`\s*\|\s*`(?P<value>[^`]*)`\s*\|\s*(?P<lanes>\d+)\s*\|\s*(?P<verdict>\S+)\s*\|"
)

#: Untergrenze, gemessen am 2026-08-29: 2 Variablen ueber 71 Workflow-Dateien.
#: Bewusst eine Untergrenze und keine exakte Zahl -- das Repo waechst, aber ein
#: Absturz auf eine Handvoll Dateien waere ein blind gewordener Scanner.
_MIN_VARIABLES = 2
_MIN_FILES = 30


def judge(evidence: Any, entry) -> Verdict:  # entry ist Teil des Urteiler-Vertrags
    log = ""
    if isinstance(evidence, dict):
        log = str(evidence.get("log") or "")
    elif isinstance(evidence, str):
        log = evidence

    if not log.strip():
        return Verdict(
            "FAIL",
            branch="log_empty",
            detail="kein Job-Log — ueber die Wirkung der Sonde sagt das nichts",
        )

    if _TABLE_HEADER not in log:
        return Verdict(
            "FAIL",
            branch="no_report_table",
            detail=(
                "die Bericht-Tabelle fehlt im Log. Entweder lief die alte Fassung, "
                "oder die Sonde brach vor dem Urteil ab — in beiden Faellen ist die "
                "Wirkung dieser Aenderung nicht belegt"
            ),
        )

    scope = _SCOPE_RE.search(log)
    if scope is None:
        return Verdict(
            "FAIL",
            branch="no_scope_line",
            detail="die Zeile mit dem gemessenen Umfang fehlt — der Umfang ist unbelegt",
        )

    n_vars = int(scope.group("vars"))
    n_files = int(scope.group("files"))
    if n_vars < _MIN_VARIABLES or n_files < _MIN_FILES:
        return Verdict(
            "FAIL",
            branch="scope_collapsed",
            detail=(
                f"Ableitung fand nur {n_vars} Variable(n) ueber {n_files} Datei(en) "
                f"(erwartet >= {_MIN_VARIABLES} / >= {_MIN_FILES}). Eine geschrumpfte "
                "Population urteilt ueber fast nichts und meldet trotzdem Erfolg"
            ),
        )

    rows = list(_ROW_RE.finditer(log))
    if len(rows) < n_vars:
        return Verdict(
            "FAIL",
            branch="rows_missing",
            detail=(
                f"{n_vars} Variablen abgeleitet, aber nur {len(rows)} Urteilszeile(n) "
                "gerendert — fuer mindestens eine Variable fiel kein Urteil"
            ),
        )

    verdicts = {row.group("name"): row.group("verdict") for row in rows}
    return Verdict(
        "PASS",
        branch="scope_measured_and_judged",
        detail=(
            f"{n_vars} Variable(n) ueber {n_files} Workflow-Datei(en) abgeleitet und "
            f"beurteilt: {verdicts}"
        ),
    )
