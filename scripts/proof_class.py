#!/usr/bin/env python3
"""Leite die beweispflichtige Dateiklasse ab — Code, den ein Workflow
ausfuehrt und den keine Testdatei importiert.

Warum ABGELEITET und nicht aufgezaehlt: Eine hartkodierte Liste faengt genau
die Drift nicht, vor der sie warnt. Gemessen am 2026-08-22 an
``tv-post-mutation-verify.yml``, dessen Kopplungstest acht ``mutations``-Felder
hartkodiert hielt — #5013 fuegte ein neuntes hinzu, der Test blieb gruen, der
Waechter war nicht mehr erschoepfend.

Der Schnitt: Ein Test, der eine Datei importiert, macht ihre Wirkung sichtbar.
Was nur im Workflow laeuft und von keinem Test angefasst wird, zeigt sich
ausschliesslich im echten Lauf — genau dort braucht es einen Ledger-Eintrag.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.proof_ledger import class_floors

ROOT = Path(__file__).resolve().parents[1]

#: Dateiendungen, die als ausfuehrbarer Code zaehlen. `.pine` ist ABSICHTLICH
#: nicht dabei: Pine-Quellen sind Daten, die ein Workflow publiziert, kein Code,
#: den er ausfuehrt. Ohne diese Grenze faellt der Library-Refresh-Bot mit ~16
#: Merges am Tag in die Klasse und der Mechanismus ist tot geboren (Task 0).
_CODE_SUFFIXES = (".py", ".ts", ".sh", ".mjs")

#: Referenzen auf Repo-Dateien in einem `run:`-Block.
_REF = re.compile(
    r"(?<![\w./-])((?:scripts|automation|tools|services)/[\w./-]+"
    r"\.(?:py|ts|sh|mjs))(?![\w/])"
)
#: `python -m scripts.foo` — Modulform, die keinen Pfad schreibt.
_MODULE_REF = re.compile(r"python3?\s+-m\s+((?:scripts|tools)\.[\w.]+)")

#: Ein Test, der eine Datei als TEXT liest und Teilstrings pinnt, sieht ihre
#: Bytes — nicht ihre Wirkung. Gemessen 2026-08-23 an
#: tests/test_workflow_tv_save_consumer_source_contract.py: 20 woertliche
#: Vorkommen des Pfades von tv_batch_consumer_rollout.ts, kein einziger Aufruf.
#: Wer solche Nennungen als Deckung zaehlt, nimmt ausgerechnet das Skript aus
#: der Klasse, das am 2026-08-22 das gehandelte Layout zerlegt hat.
_TS_IMPORT = re.compile(r"""(?:from|require\(|import\()\s*['"]([^'"]+)['"]""")
_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+((?:scripts|tools)[\w.]*)", re.M)


class ProofClassError(Exception):
    """Die Ableitung hat ihre Untergrenze unterschritten."""


def workflow_files(root: Path = ROOT) -> frozenset[str]:
    """Alle Workflow-Definitionen, repo-relativ."""
    wf_dir = root / ".github" / "workflows"
    return frozenset(
        p.relative_to(root).as_posix()
        for p in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))
    )


def referenced_code(root: Path = ROOT) -> frozenset[str]:
    """Repo-Dateien, die irgendein Workflow ausfuehrt."""
    hits: set[str] = set()
    for rel in workflow_files(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        hits.update(_REF.findall(text))
        for module in _MODULE_REF.findall(text):
            candidate = Path(*module.split(".")).with_suffix(".py")
            hits.add(candidate.as_posix())
    return frozenset(h for h in hits if (root / h).exists())


def test_imported(root: Path = ROOT) -> frozenset[str]:
    """Dateien, die eine Testdatei IMPORTIERT — nicht solche, die sie nur nennt.

    Die Unterscheidung ist der Kern: ein Kontrakttest, der Quelltext als String
    pint, beobachtet keine Ausfuehrung. Er gehoert nicht zur Deckung.
    """
    named: set[str] = set()
    for tests_dir in ((root / "tests"), (root / "automation")):
        if not tests_dir.exists():
            continue
        for path in tests_dir.rglob("*"):
            if not path.is_file():
                continue
            if not (path.name.startswith("test_") or ".test." in path.name):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for spec in _TS_IMPORT.findall(text):
                named.add(Path(spec).name)
                named.add(Path(spec).stem)
            for module in _PY_IMPORT.findall(text):
                rel = Path(*module.split(".")).with_suffix(".py").as_posix()
                named.add(rel)
                named.add(Path(rel).stem)
    return frozenset(named)


def derive_class(root: Path = ROOT) -> frozenset[str]:
    """Die beweispflichtige Klasse. Wirft, wenn eine Zwischenmenge zu klein ist."""
    floors = class_floors()
    workflows = workflow_files(root)
    if len(workflows) < floors["workflows"]:
        raise ProofClassError(
            f"Untergrenze verletzt: {len(workflows)} Workflows < {floors['workflows']}"
        )
    referenced = referenced_code(root)
    if len(referenced) < floors["referenced_code"]:
        raise ProofClassError(
            f"Untergrenze verletzt: {len(referenced)} referenzierte Dateien "
            f"< {floors['referenced_code']}"
        )
    covered = test_imported(root)
    unseen = {
        rel
        for rel in referenced
        if rel.endswith(_CODE_SUFFIXES)
        and rel not in covered
        and Path(rel).stem not in covered
    }
    derived = frozenset(unseen | workflows)
    if len(derived) < floors["derived_class"]:
        raise ProofClassError(
            f"Untergrenze verletzt: Klasse hat {len(derived)} Eintraege "
            f"< {floors['derived_class']}"
        )
    return derived


def main() -> int:
    for rel in sorted(derive_class()):
        print(rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
