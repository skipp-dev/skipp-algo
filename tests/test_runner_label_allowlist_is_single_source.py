"""Die Allowlist ist die Quelle -- YAML und Doku sind daran gepinnt.

Warum es diesen File gibt
=========================

Nach #5171 stand die Liste der erlaubten arm64-Labels an drei Stellen: im
``case``-Block von ``ci.yml``, in der Tabelle des Runner-Entscheidungsdokuments
und im Test. Drei Kopien ohne Mechanismus sind ein Doppelgaenger: die Doku darf
still veralten, waehrend YAML und Test sich einig sind, und niemand merkt es.

Seit 2026-08-29 ist ``.github/runner_label_allowlist.json`` die Quelle. Die
beiden Kopien bleiben bewusst bestehen:

* ``ci.yml`` behaelt seinen literalen ``case``-Block, weil der
  ``runner-preflight``-Job vier *required* Shards gatet und dafuer in ~4 s ohne
  Checkout und ohne ``jq`` fertig sein soll. Der Preis -- eine Kopie -- wird hier
  bezahlt, nicht verschwiegen.
* Die Doku traegt eine Tabelle, weil ein Runbook, das auf eine JSON-Datei
  verweist statt die Werte zu nennen, um 3 Uhr nachts nichts wert ist.

Was diesen File von einer blossen Zusicherung unterscheidet: die Testwerte sind
**unabhaengig** notiert (``_ARM_LABELS`` unten), nicht aus der Datei gelesen. Ein
Test, der seine Erwartung aus dem Prueflung ableitet, ist mit jeder Aenderung
automatisch einverstanden -- er pinnt nichts, er echot.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_ALLOWLIST = _ROOT / ".github" / "runner_label_allowlist.json"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_DOC = _ROOT / "docs" / "engineering-program" / "runner_hosted_vs_selfhosted_decision.md"

#: Unabhaengiger Zeuge, von Hand notiert. Aendert sich die Allowlist wirklich,
#: gehoert diese Zeile in denselben Commit -- genau das ist der Punkt.
_ARM_LABELS = ("ubuntu-24.04-arm", "ubuntu-22.04-arm")
_HOSTED_LABELS = (
    "ubuntu-latest",
    "ubuntu-24.04",
    "ubuntu-22.04",
    "ubuntu-24.04-4core",
    "ubuntu-24.04-8core",
)


def _allowlist() -> dict:
    return json.loads(_ALLOWLIST.read_text(encoding="utf-8"))["variables"]


def test_allowlist_matches_the_independent_witness() -> None:
    variables = _allowlist()
    assert tuple(variables["SMC_CI_ARM_RUNNER"]["allowed"]) == _ARM_LABELS, (
        "Allowlist fuer SMC_CI_ARM_RUNNER weicht vom Zeugen in diesem File ab. "
        "Wenn die Aenderung gewollt ist, gehoert sie in denselben Commit — sonst "
        "ist die Liste gewachsen, ohne dass jemand hingesehen hat."
    )
    assert tuple(variables["SMC_GH_HOSTED_RUNNER"]["allowed"]) == _HOSTED_LABELS, (
        "Allowlist fuer SMC_GH_HOSTED_RUNNER weicht vom Zeugen in diesem File ab."
    )


def test_ci_preflight_case_block_matches_the_allowlist() -> None:
    """Die Kopie in ci.yml darf nicht driften.

    Gelesen wird der ``case``-Block strukturell aus dem Step, nicht als Substring
    irgendwo in der Datei: ein Label in einem Kommentar soll diesen Test NICHT
    gruen machen.
    """
    doc = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = doc["jobs"]["runner-preflight"]["steps"]
    run_blocks = [s.get("run", "") for s in steps if "run" in s]
    assert run_blocks, "runner-preflight hat keinen run-Block mehr"
    block = "\n".join(run_blocks)

    match = re.search(r"^\s*([a-z0-9.|-]+)\)\s*;;\s*$", block, re.M)
    assert match, (
        "im runner-preflight ist kein `<labels>) ;;`-Zweig mehr zu finden — "
        f"entweder ist die Allowlist-Pruefung weg oder sie hat eine neue Form:\n{block}"
    )
    in_yaml = tuple(match.group(1).split("|"))
    allowed = tuple(_allowlist()["SMC_CI_ARM_RUNNER"]["allowed"])
    assert in_yaml == allowed, (
        f"ci.yml akzeptiert {in_yaml!r}, die Allowlist erlaubt {allowed!r} — "
        "eine der beiden Seiten wurde ohne die andere geaendert"
    )


def test_doc_table_lists_exactly_the_allowed_labels() -> None:
    """Das Runbook nennt die Werte, und zwar dieselben.

    Ohne diesen Test ist die Doku die Kopie, die zuerst veraltet: sie hat keinen
    Konsumenten, der sie ausfuehrt.
    """
    text = _DOC.read_text(encoding="utf-8")
    variables = _allowlist()

    for name, entry in variables.items():
        assert f"`{name}`" in text, f"{_DOC.name} nennt die Variable {name} nicht"
        for label in entry["allowed"]:
            assert f"`{label}`" in text, (
                f"{_DOC.name} nennt den erlaubten Wert `{label}` fuer {name} nicht — "
                "das Runbook ist hinter der Allowlist zurueckgeblieben"
            )

    # Gegenrichtung: die Doku darf keinen Wert als erlaubt fuehren, den die
    # Allowlist nicht kennt. Sonst setzt jemand ihn und wundert sich ueber einen
    # Lauf, der nie startet.
    every_allowed = {label for entry in variables.values() for label in entry["allowed"]}
    section = text.split("### `SMC_CI_ARM_RUNNER`", 1)
    assert len(section) == 2, f"{_DOC.name} hat den SMC_CI_ARM_RUNNER-Abschnitt nicht mehr"
    mentioned = re.findall(r"`(ubuntu-[a-z0-9.-]+)`", section[1])
    # Ohne diese Zeile wuerde die Schleife darunter bei einer umformatierten Doku
    # ueber null Elemente laufen und trotzdem gruen melden.
    assert mentioned, (
        f"{_DOC.name} nennt im SMC_CI_ARM_RUNNER-Abschnitt gar kein `ubuntu-*`-Label "
        "mehr — die Gegenrichtung dieses Tests wuerde vakuum durchlaufen"
    )
    for label in mentioned:
        assert label in every_allowed or label == "ubuntu-latest-arm", (
            f"{_DOC.name} nennt `{label}`, das steht nicht auf der Allowlist"
        )


def test_every_allowlist_entry_carries_a_reason() -> None:
    """Ein Eintrag ohne Begruendung ist eine Zahl ohne Herkunft."""
    for name, entry in _allowlist().items():
        note = entry.get("note", "")
        assert len(note.strip()) >= 40, f"{name}: `note` fehlt oder ist zu duenn ({note!r})"
