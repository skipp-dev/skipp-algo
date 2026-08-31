"""Der Nummern-Waechter darf nicht anklagen, was der MERGE-Checkout mitbringt.

Gemessen am 2026-08-31 an PR #5217. Der PR fuegt genau EINEN Beweis-Eintrag
hinzu (``id = "5217"``). Trotzdem meldete fast-gates::

    Beweis-Eintrag mit fremder PR-Nummer: ['5218'] — dieser PR ist #5217.

Ursache: ``fast-gates`` checkt ``refs/remotes/pull/<n>/merge`` aus -- den Branch
PLUS dem aktuellen ``main``. Der Waechter las die vorhandenen Ids aus dem
ARBEITSBAUM und verglich sie gegen die Merge-Basis. Alles, was seit dem Oeffnen
des PR auf main landete, stand damit im Baum und sah aus wie "von diesem PR
hinzugefuegt". #5217 wurde um 07:43Z geoeffnet, #5218 landete um 09:41Z auf
main -- ein voellig korrekter PR wurde blockiert.

Das trifft JEDEN PR, der hinter main liegt, waehrend main einen Beweis-Eintrag
bekommt. In diesem Repo ist das Routine, nicht Ausnahme.

WARUM DIE BESTEHENDEN TESTS ES NICHT FINGEN: sie pruefen ``guessed_pr_numbers``
als reine Funktion -- korrekt, aber eine Ebene zu tief. Der Defekt lag in dem,
was ihr uebergeben wird. Dieser Test faehrt deshalb ``main()`` gegen ein echtes
Git-Repository mit echter Merge-Lage, statt die Menge selbst zu stellen.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.check_proof_ledger as cpl
import scripts.proof_ledger as pl

#: Das isolierte Ledger braucht die Pflichtabschnitte des echten, sonst
#: scheitert ``main()`` schon beim Laden (``KeyError: class_floors``) und der
#: Test misst das Laden statt die Nummernpruefung. Die Zahlen sind bewusst 0:
#: dieser Test sagt nichts ueber Klassen-Untergrenzen.
_KOPF = """[class_floors]
workflows = 0
referenced_code = 0
test_imported = 0
derived_class = 0
"""

_EINTRAG = """
[[proof]]
id     = "{pr}"
kind   = "exempt"
claim  = "Testeintrag {pr}"
state  = "AUSGENOMMEN"
due_by = "2026-12-31"
owner  = "operator"
"""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _isoliere(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Den Pruefling vollstaendig auf das Test-Repo zeigen lassen.

    ``ROOT`` allein reicht NICHT: ``proof_ledger._LEDGER_PATH`` wird beim Import
    aus ``ROOT`` berechnet und bleibt danach eingefroren. Ohne das zweite Patch
    laedt ``load_entries()`` weiter das ECHTE Ledger dieses Repos -- der Test
    liefe halb gegen den Prueflung, halb gegen die Wirklichkeit und wuerde bei
    jedem neuen Eintrag auf main anders ausfallen.
    """
    monkeypatch.setattr(cpl, "ROOT", repo)
    monkeypatch.setattr(pl, "ROOT", repo)
    monkeypatch.setattr(pl, "_LEDGER_PATH", repo / "proof_ledger.toml")
    monkeypatch.chdir(repo)


def _commit(repo: Path, text: str, message: str) -> str:
    (repo / "proof_ledger.toml").write_text(text, encoding="utf-8")
    _git(repo, "add", "proof_ledger.toml")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def merge_lage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Basis -> (Branch fuegt 5217 an | main fuegt 5218 an) -> Merge ausgecheckt.

    Genau die Lage, die fast-gates herstellt.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    # Genug Abstand zwischen den beiden Einfuegepunkten, damit git wirklich
    # MERGT statt zu kollidieren: der Branch haengt hinten an, main setzt vorn
    # ein. Ein Konflikt waere hier eine Eigenschaft der Fixture, nicht der Lage,
    # die sie nachstellen soll -- und der Test wuerde etwas anderes messen.
    basis_text = _KOPF + _EINTRAG.format(pr="1000") + "\n" * 12 + _EINTRAG.format(pr="1001")
    basis = _commit(repo, basis_text, "basis")

    _git(repo, "checkout", "-q", "-b", "feature")
    branch_head = _commit(repo, basis_text + _EINTRAG.format(pr="5217"), "branch: 5217")

    _git(repo, "checkout", "-q", "main")
    _commit(repo, _KOPF + _EINTRAG.format(pr="5218") + basis_text[len(_KOPF):], "main: 5218")

    # Der Merge-Checkout: Branch + main, so wie CI ihn baut.
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "-q", "--no-edit", "main")

    _isoliere(monkeypatch, repo)
    return {"basis": basis, "branch_head": branch_head}


def test_the_merge_checkout_really_carries_the_foreign_entry(merge_lage: dict[str, str]) -> None:
    """Positivkontrolle der FIXTURE: ohne den fremden Eintrag prueft der Test nichts."""
    text = (Path.cwd() / "proof_ledger.toml").read_text(encoding="utf-8")
    assert 'id     = "5218"' in text, "der Merge hat den fremden Eintrag nicht gebracht"
    assert 'id     = "5217"' in text, "der Branch-Eintrag fehlt"


def test_an_entry_that_arrived_via_main_is_not_blamed_on_this_pr(
    merge_lage: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Der Fall vom 2026-08-31, wortwoertlich."""
    rc = cpl.main(
        ["--range", f"{merge_lage['basis']}..{merge_lage['branch_head']}", "--pr", "5217"]
    )
    assert rc == 0, (
        "der Bereich fuegt nur 5217 hinzu; 5218 kam ueber main in den "
        f"Merge-Checkout: {capsys.readouterr().err}"
    )


def test_a_foreign_number_on_the_branch_itself_is_still_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Eine fremde Nummer AUF DEM BRANCH bleibt laut — die Zusicherung haelt.

    Ohne diesen Fall koennte der Fix den Waechter still entschaerfen -- er ist
    gegen genau das gebaut, was am 2026-08-29 main 70 Minuten blockierte.
    """
    repo = tmp_path / "repo2"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    basis_text = _KOPF + _EINTRAG.format(pr="1000")
    basis = _commit(repo, basis_text, "basis")
    _git(repo, "checkout", "-q", "-b", "feature")
    # Der Branch selbst legt eine FREMDE Nummer an — genau der Fall von #5179.
    head = _commit(repo, basis_text + _EINTRAG.format(pr="5178"), "branch: fremde Nummer")
    _isoliere(monkeypatch, repo)

    assert cpl.main(["--range", f"{basis}..{head}", "--pr", "5179"]) == 1
    assert "fremder PR-Nummer" in capsys.readouterr().err
