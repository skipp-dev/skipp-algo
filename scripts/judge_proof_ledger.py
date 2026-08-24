#!/usr/bin/env python3
"""Hole je Ledger-Eintrag den Zeugen, urteile, melde Widersprueche.

Dies ist die netzgebundene Haelfte. Sie laeuft im scheduled Workflow, nie in
fast-gates: der einzige required Check darf nicht von der GitHub-API abhaengen
(``scripts/check_proof_ledger.py`` bleibt netzlos und diff-bezogen).

Der Monitor schreibt das Ledger NICHT zurueck. Zustandsaenderungen macht ein
Mensch im PR, wo das Offline-Gate sie prueft. Ein Bot mit Schreibrecht auf die
Beweisfuehrung ist genau die Konstruktion, durch die der Library-Refresh-Bot
am 31.7. zweimal durch den R1-Vertrag gelaufen ist.

Zeugensuche: nach ``started_at`` des benannten JOBS fragen, nie nach
``head_sha``. Der Save-Workflow hat einen Fast-forward-Schritt, ein Lauf misst
also mit dem main-Stand seines Job-Starts. Wer head_sha nimmt, verwirft
gueltige Zeugen und wartet auf einen Beweis, den er selbst wegdefiniert hat.

Nie ueber die Lauf-Conclusion urteilen: Lauf 32620808573 (2026-08-23) war
``conclusion: failure`` und hat dabei exakt das Richtige getan -- deshalb
prueft ``newest_witness`` nur auf ``status=="completed"``, nie auf
``conclusion``.

Der Monitor urteilt NUR ueber Eintraege mit ``evidence_source == "artifact"``
(er holt Artefakte, keine Job-Logs). Eintraege mit ``evidence_source ==
"job_log"`` (aktuell #5018, #5027) werden strukturell uebersprungen, nicht
negativ beurteilt -- und die Ausgabe sagt das (``unjudged_reason``), statt
sie stillschweigend wie "kein Zeuge gefunden" aussehen zu lassen. Eine
uebersprungene Pruefung, die wie eine bestandene aussieht, ist genau der
Defekt, gegen den dieses ganze Vorhaben gebaut wurde.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.proof_judges import Verdict, load_judge
from scripts.proof_ledger import TERMINAL_STATES, ProofEntry, load_entries

REPO = "skipp-dev/skipp-algo"


def classify(entry: ProofEntry, verdict: Verdict | None, today: str) -> str:
    """``OK`` | ``UEBERFAELLIG`` | ``WIDERSPRUCH``."""
    if verdict is not None:
        declared_good = entry.state == "PASS"
        measured_bad = verdict.state in {"FAIL", "STEHT_AUS"}
        if declared_good and measured_bad:
            return "WIDERSPRUCH"
        if entry.state == "UNERREICHBAR" and verdict.state in {"PASS", "FAIL"}:
            return "WIDERSPRUCH"
    if entry.state in TERMINAL_STATES:
        return "OK"
    if dt.date.fromisoformat(entry.due_by) < dt.date.fromisoformat(today):
        return "UEBERFAELLIG"
    return "OK"


def _gh(*args: str) -> str:
    proc = subprocess.run(  # noqa: S603
        ["gh", *args],  # noqa: S607
        capture_output=True, text=True, check=False,
    )
    return proc.stdout if proc.returncode == 0 else ""


def newest_witness(entry: ProofEntry) -> str:
    """Lauf-Id des juengsten Laufs, dessen Zeugen-JOB nach dem Merge startete."""
    raw = _gh(
        "api",
        f"repos/{REPO}/actions/workflows/{entry.witness}.yml/runs?per_page=50",
        "-q",
        '.workflow_runs[] | select(.status=="completed") | .id',
    )
    for run_id in raw.split():
        started = _gh(
            "api",
            f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100",
            "-q",
            f'[.jobs[] | select(.name=="{entry.witness_job}") | .started_at][0] // ""',
        ).strip()
        # Auf FORM pruefen, nicht auf "nicht leer". `gh api` schreibt seinen
        # Fehler-Body zwar nach STDOUT -- gemessen 2026-08-24: ein echter 404
        # liefert `returncode=1` und `{"message":"Not Found",...}` auf STDOUT
        # -- aber _gh() oben filtert genau darauf (`if proc.returncode == 0
        # else ""`), ein 404 erreicht diesen Vergleich ueber DIESEN Aufrufpfad
        # also gar nicht. Die Formpruefung ist trotzdem die ZWEITE,
        # unabhaengige Verteidigungslinie: sollte _gh()s Rueckgabecode-Filter
        # je entfernt werden oder ein anderer Aufrufer ein rohes `gh`-Ergebnis
        # hierher reichen, waere ein reiner Nicht-leer-/Groessenvergleich
        # verwundbar -- '{' ist ASCII-groesser als jede Ziffer, ein
        # JSON-Fehlerkoerper wuerde jeden echten Zeitstempel schlagen.
        # test_newest_witness_never_crowns_a_json_error_body_as_a_witness
        # haelt genau das fest, unabhaengig vom _gh()-Filter.
        if len(started) != 20 or not started.endswith("Z") or not started[:4].isdigit():
            continue
        if started > (entry.raw or {}).get("merged_at", ""):
            return str(run_id)
    return ""


def unjudged_reason(entry: ProofEntry) -> str:
    """Warum dieser Eintrag NICHT durch den Monitor beurteilt wird.

    Leer, solange der Eintrag zu den beurteilbaren gehoert -- dann versucht
    ``main()`` wirklich, einen Zeugen zu holen. Nicht leer bedeutet: dieser
    Eintrag wird strukturell uebersprungen, egal was passiert. Der Aufrufer
    haengt den Grund an ``measured`` an (``KEIN_URTEIL (<grund>)``) statt den
    Eintrag wie einen erfolglosen Zeugensuchversuch (``KEIN_ZEUGE``) aussehen
    zu lassen -- genau die Verwechslung, die dieses Ledger verhindern soll.
    """
    if entry.kind != "fix":
        return "kein fix-Eintrag"
    if not entry.judge:
        return "kein Urteiler deklariert"
    if entry.evidence_source == "job_log":
        return "job_log — Monitor holt keine Logs"
    if entry.evidence_source != "artifact":
        return f"evidence_source={entry.evidence_source!r} unbekannt"
    return ""


def _judge_entry(entry: ProofEntry) -> tuple[Verdict | None, str]:
    """``(Urteil, Lauf-Id)`` fuer einen beurteilbaren Eintrag. Holt Zeugen,
    laedt das Artefakt herunter, urteilt. ``Verdict`` bleibt ``None``, wenn
    kein Zeuge gefunden wurde oder das Artefakt keine gueltige Evidenz traegt.

    Der Dateiname im Artefakt wird aus ``entry.artifact`` abgeleitet
    (Bindestrich zu Unterstrich, ``.json`` angehaengt) statt hartkodiert --
    jedes ``actions/upload-artifact``-Ziel in diesem Repo (``tradingview-
    consumer-bindings`` -> ``tradingview_consumer_bindings.json``,
    ``proof-ledger-monitor-report`` -> ``proof_ledger_monitor_report.json``)
    folgt dieser Konvention. Eine Hartkodierung auf den ERSTEN Eintrag waere
    fuer jeden weiteren artifact-Eintrag stumm falsch gewesen.
    """
    run_id = newest_witness(entry)
    if not run_id:
        return None, ""
    with tempfile.TemporaryDirectory(prefix="proof_ledger_") as tmp_dir:
        _gh(
            "run", "download", run_id, "-R", REPO,
            "-n", entry.artifact, "-D", tmp_dir,
        )
        artifact_filename = entry.artifact.replace("-", "_") + ".json"
        artifact_path = Path(tmp_dir) / artifact_filename
        try:
            with artifact_path.open(encoding="utf-8") as fh:
                evidence = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None, run_id
    return load_judge(entry.judge).judge(evidence, entry), run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=dt.date.today().isoformat())
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for entry in load_entries():
        verdict: Verdict | None = None
        run_id = ""
        skip_reason = unjudged_reason(entry)
        if not skip_reason:
            verdict, run_id = _judge_entry(entry)

        if verdict is not None:
            measured = verdict.state
        elif skip_reason:
            measured = f"KEIN_URTEIL ({skip_reason})"
        else:
            measured = "KEIN_ZEUGE"

        rows.append(
            {
                "id": entry.id,
                "kind": entry.kind,
                # Traegt die Ehrlichkeits-Zusicherung nach AUSSEN: ein
                # Selbst-Urteiler (scripts/proof_judges/proof_ledger_monitor_self.py)
                # prueft am eigenen Report, dass ein uebersprungener Eintrag
                # (evidence_source != "artifact") nie als KEIN_ZEUGE erscheint.
                "evidence_source": entry.evidence_source,
                "declared": entry.state,
                "measured": measured,
                "branch": verdict.branch if verdict else "",
                "run": run_id,
                "owner": entry.owner,
                "due_by": entry.due_by,
                "class": classify(entry, verdict, args.today),
            }
        )

    loud = [r for r in rows if r["class"] != "OK"]
    for row in rows:
        print(
            f"{row['class']:14s} {row['id']:24s} deklariert={row['declared']:12s} "
            f"gemessen={row['measured']:44s} faellig={row['due_by']} ({row['owner']})"
        )
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, sort_keys=True)
    if loud:
        print(f"\n{len(loud)} Eintrag/Eintraege brauchen einen Menschen.", file=sys.stderr)
    return 1 if loud else 0


if __name__ == "__main__":
    raise SystemExit(main())
