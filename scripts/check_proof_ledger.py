#!/usr/bin/env python3
"""Fail a PR that changes proof-bearing code without declaring a proof.

Diff-bezogen und ohne Netz, aus zwei Gruenden, die beide gemessen sind:

* **Diff statt Ist-Zustand.** ``check_r1_attested_sources.py`` hat es
  vorgemacht: main ist bereits driftend, ein Zustandscheck hier wuerde jeden
  PR rot machen, auch den, der repariert.
* **Kein Netz.** fast-gates ist der EINZIGE required Check (ADR-0011). Ein
  Wachter, der die GitHub-API befragt, macht den Merge-Pfad von API-Zustand
  und Actions-Budget abhaengig. Alles Netzgebundene lebt im Monitor-Workflow.

Als Modul aufrufen: ``python -m scripts.check_proof_ledger --range A..B``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib

from scripts.proof_class import derive_class
from scripts.proof_ledger import ROOT, TERMINAL_STATES, ProofLedgerError, load_entries

_REMEDY = """
Dieser PR aendert Code, dessen Wirkung die Testsuite prinzipiell nicht sehen
kann — er laeuft nur in einem Workflow, und kein Test importiert ihn.

Trage in proof_ledger.toml einen Eintrag nach:

  [[proof]]
  id              = "<PR-Nummer>"
  kind            = "fix"
  merged_at       = "<wird beim Merge nachgetragen>"
  merge_sha       = "<dito>"
  claim           = "<was soll diese Aenderung bewirken>"
  witness         = "<Workflow, der einen Zeugen erzeugt>"
  witness_job     = "<Job, dessen started_at zaehlt — NIE head_sha>"
  evidence_source = "artifact"        # oder "job_log"
  artifact        = "<Artefaktname>"
  version_probe   = "<Feld, das es erst seit dieser Aenderung gibt>"
  judge           = "<Modul unter scripts/proof_judges/>"
  state           = "OFFEN"
  due_by          = "<YYYY-MM-DD>"
  owner           = "<wer misst nach>"

Braucht die Aenderung keinen Beweis (Kommentar, Umbenennung, Formatierung),
dann sag das ausdruecklich statt es wegzulassen:

  [[proof]]
  id     = "<PR-Nummer>"
  kind   = "exempt"
  claim  = "<warum hier nichts zu beweisen ist>"
  state  = "AUSGENOMMEN"
  due_by = "<Merge-Datum, ohne Wirkung>"
  owner  = "<wer das entschieden hat>"
""".strip()


def _merge_base_range(commit_range: str) -> str:
    """``A..B`` zu ``A...B`` weiten, damit der Diff an der Merge-Basis beginnt.

    ``git diff A..B`` ist kein Bereich, sondern ein Vergleich zweier BAEUME.
    Auf einem PR-Branch, der aelter ist als eine Aenderung auf main, meldet er
    mains Aenderung als die dieses PRs — gemessen am 2026-08-04 an #4373.
    """
    if "..." in commit_range:
        return commit_range
    if ".." in commit_range:
        return commit_range.replace("..", "...", 1)
    return commit_range


def _changed_files(commit_range: str) -> frozenset[str]:
    proc = subprocess.run(  # noqa: S603
        ["git", "diff", "--name-only", _merge_base_range(commit_range)],  # noqa: S607
        capture_output=True, text=True, check=True, cwd=ROOT,
    )
    return frozenset(line.strip() for line in proc.stdout.splitlines() if line.strip())


def _ledger_ids_at(rev: str) -> frozenset[str]:
    """Eintrags-Ids, wie sie bei ``rev`` standen. Leer, wenn es sie nicht gab."""
    proc = subprocess.run(  # noqa: S603
        ["git", "show", f"{rev}:proof_ledger.toml"],  # noqa: S607
        # check=False (deliberate): a non-zero rc here means the file did not
        # exist at `rev` (e.g. proof_ledger.toml is not yet on main) -- an
        # EXPECTED outcome this function turns into an empty set below, not
        # an error to raise on.
        capture_output=True, text=True, check=False, cwd=ROOT,
    )
    if proc.returncode != 0:
        return frozenset()
    data = tomllib.loads(proc.stdout)
    return frozenset(str(e["id"]) for e in data.get("proof", []) if e.get("id"))


def _coupling_failures() -> list[str]:
    """Begruendungen, die ins Leere zeigen.

    Eine Deklaration, die niemand pruefen kann, ist ein Wort — und ein Wort
    laesst sich umschreiben, um einen Beweis stillzulegen. Das Muster stammt
    aus ``_DEPLOYMENT_IS_CONFIGURED``: die Deklaration ist nur ehrlich,
    solange die Sache existiert, auf die sie sich beruft.

    Zweite Kopplungsart seit 2026-08-24: ``refutation_tracked_by`` auf einem
    ``state == "FAIL"``-Eintrag muss auf einen ANDEREN Ledger-Eintrag zeigen,
    der ``kind == "defect"`` ist und NICHT-terminal steht. Verschwindet der
    Halter oder wird er terminal (PASS/FAIL/UNERREICHBAR/AUSGENOMMEN), ist die
    Quittung ungueltig und der Waechter macht den PR rot — ohne diese Probe
    waere ``refutation_tracked_by`` ein Schalter zum Stummstellen, den niemand
    prueft, sobald der Halter erledigt oder geloescht wird.
    """
    problems: list[str] = []
    entries = load_entries()
    by_id = {entry.id: entry for entry in entries}
    for entry in entries:
        ref = entry.unreachable_because
        if ref:
            kind, _, rest = ref.partition(":")
            if kind == "path":
                if not (ROOT / rest).exists():
                    problems.append(f"{entry.id}: Pfad {rest!r} existiert nicht mehr")
            elif kind == "symbol":
                rel, _, name = rest.partition("#")
                target = ROOT / rel
                if not target.exists():
                    problems.append(f"{entry.id}: Datei {rel!r} existiert nicht mehr")
                elif name not in target.read_text(encoding="utf-8", errors="replace"):
                    problems.append(
                        f"{entry.id}: Symbol {name!r} steht nicht mehr in {rel!r} — "
                        "die Begruendung traegt nicht mehr"
                    )
            else:
                problems.append(f"{entry.id}: unbekannte Kopplungsart {kind!r}")

        holder_id = entry.refutation_tracked_by
        if not holder_id:
            continue
        holder = by_id.get(holder_id)
        if holder is None:
            problems.append(
                f"{entry.id}: refutation_tracked_by {holder_id!r} existiert "
                "nicht im Ledger"
            )
        elif holder.kind != "defect":
            problems.append(
                f"{entry.id}: refutation_tracked_by {holder_id!r} ist kein "
                f"defect-Eintrag (kind={holder.kind!r})"
            )
        elif holder.state in TERMINAL_STATES:
            problems.append(
                f"{entry.id}: refutation_tracked_by {holder_id!r} steht auf "
                f"einem terminalen Zustand ({holder.state!r}) — die Quittung "
                "ist ungueltig"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", dest="commit_range", required=True)
    args = parser.parse_args(argv)

    try:
        entries = load_entries()
    except ProofLedgerError as exc:
        print(f"proof_ledger.toml ist nicht wohlgeformt: {exc}", file=sys.stderr)
        return 2

    problems = _coupling_failures()
    if problems:
        print("Ledger-Begruendungen, die nicht mehr tragen:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1

    touched = sorted(_changed_files(args.commit_range) & derive_class())
    if not touched:
        return 0

    base = _merge_base_range(args.commit_range).split("...")[0]
    before = _ledger_ids_at(base)
    after = frozenset(entry.id for entry in entries)
    if after - before:
        return 0

    print("Beweispflichtige Dateien in diesem PR:", file=sys.stderr)
    for rel in touched:
        print(f"  {rel}", file=sys.stderr)
    print("", file=sys.stderr)
    print(_REMEDY, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
