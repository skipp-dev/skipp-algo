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


def _merge_base_commit(commit_range: str) -> str:
    """Der echte Merge-Basis-COMMIT von ``A..B``/``A...B`` -- fuer ``git show
    <rev>:datei``, das einen einzelnen Commit braucht, keinen Bereich.

    ``_merge_base_range`` weitet ``A..B`` zu ``A...B``, was fuer ``git diff``
    richtig ist (ein Vergleich zweier Baeume). Aber die linke Seite dieser
    Zeichenkette ist NICHT die Merge-Basis -- sie ist der literale Anfang des
    uebergebenen Bereichs (in fast-gates ``github.event.pull_request.base.sha``).
    Mergt ein PR main in seinen eigenen Branch (BEHIND-Aufloesung, Routine in
    diesem Repo), enthaelt ``git show base.sha:proof_ledger.toml`` bereits
    jeden main-Eintrag bis zu diesem literalen SHA, obwohl der PR-Branch
    selbst keinen neuen Eintrag hinzugefuegt hat -- der PR erbt die
    Beweispflicht-Erfuellung eines fremden PRs. ``git merge-base`` liefert den
    tatsaechlichen gemeinsamen Vorfahren, unabhaengig davon, was seither in
    den PR-Branch gemergt wurde.
    """
    widened = _merge_base_range(commit_range)
    if "..." in widened:
        left, right = widened.split("...", 1)
    else:
        left = right = widened
    proc = subprocess.run(  # noqa: S603
        ["git", "merge-base", left, right],  # noqa: S607
        capture_output=True, text=True, check=True, cwd=ROOT,
    )
    return proc.stdout.strip()


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


def guessed_pr_numbers(added_ids: frozenset[str], pr_number: str) -> list[str]:
    """Welche neu angelegten numerischen ids gehoeren NICHT zu diesem PR?

    Warum das geprueft wird (2026-08-29, ein bezahlter Ausfall):
    PR #5179 legte seinen Eintrag unter ``id = "5178"`` an -- seine eigene Nummer
    war 5179, die Nummer war beim Anlegen GERATEN, und 5178 war zu dem Zeitpunkt
    bereits belegt. Der Loader lehnt das Ledger bei doppelter id KOMPLETT ab:
    17 Tests rot, ``main`` 70 Minuten blockiert, jeder offene PR mit dazu.

    Beide PRs waren fuer sich gruen. Die Checks von #5179 liefen auf einer Basis
    VOR dem Merge des anderen und konnten die Kollision strukturell nicht sehen
    -- kein Review-Versaeumnis, sondern die Stale-Check-Falle. Ein
    Kollisions-Test haette sie deshalb auch nicht gefangen; was faengt, ist die
    Frage, ob die Nummer ueberhaupt die EIGENE ist. Die kann jeder PR fuer sich
    allein beantworten.

    Symbolische ids (``refresh-surface-hold``, ``klasse-h``-Halter) sind
    ausgenommen: sie referenzieren keinen PR und koennen deshalb auch keinen
    fremden treffen.
    """
    return sorted(
        added
        for added in added_ids
        if added.isdigit() and added != pr_number
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", dest="commit_range", required=True)
    parser.add_argument(
        "--pr",
        dest="pr_number",
        default="",
        help=(
            "Nummer des PRs, der diesen Bereich beitraegt. Gesetzt erzwingt sie, "
            "dass jede neu angelegte NUMERISCHE Beweis-id genau diese Nummer ist."
        ),
    )
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

    after = frozenset(entry.id for entry in entries)

    # VOR dem `touched`-Ausstieg, aber NUR wenn eine PR-Nummer vorliegt: ein PR
    # kann einen Eintrag anlegen, ohne selbst beweispflichtige Dateien zu
    # beruehren (der Ausfall vom 2026-08-29 war genau so ein `exempt`-Eintrag).
    # Stuende die Pruefung unter dem Ausstieg, waere sie fuer den Fall blind,
    # der sie ausgeloest hat. Die `merge-base`-Aufloesung bleibt bewusst INNEN:
    # ohne `--pr` (main-Push, merge_group, Aufrufe mit synthetischem Bereich)
    # darf sich am bisherigen Verhalten nichts aendern.
    if args.pr_number:
        added = after - _ledger_ids_at(_merge_base_commit(args.commit_range))
        fremd = guessed_pr_numbers(added, args.pr_number)
        if fremd:
            print(
                f"Beweis-Eintrag mit fremder PR-Nummer: {fremd} — dieser PR ist "
                f"#{args.pr_number}.",
                file=sys.stderr,
            )
            print(
                "Eine geratene Nummer kann eine bereits belegte treffen. Der "
                "Loader lehnt das Ledger dann KOMPLETT ab (`doppelte id`), und "
                "main faellt fuer alle offenen PRs aus — am 2026-08-29 70 "
                "Minuten lang. id auf die eigene PR-Nummer setzen.",
                file=sys.stderr,
            )
            return 1

    touched = sorted(_changed_files(args.commit_range) & derive_class())
    if not touched:
        return 0

    base = _merge_base_commit(args.commit_range)
    before = _ledger_ids_at(base)
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
