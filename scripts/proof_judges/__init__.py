#!/usr/bin/env python3
"""Vertrag fuer reine Urteiler ueber Beweis-Evidenz.

Ein Urteiler bekommt Evidenz und einen Ledger-Eintrag und gibt ein Urteil
zurueck. Er holt nichts, er schreibt nichts, er kennt keine Uhr — nur so ist
er gegen ein Korpus laufbar. Der Bash-Urteiler, den das hier abloest, war
nicht laufbar, und genau deshalb konnte einer seiner Zweige einen Tag lang
Urteile drucken, ohne je feuern zu koennen.

Jeder Zweig traegt ein LABEL (``branch=``). Die Labels werden in Task 5 per
AST aus dem Quelltext abgeleitet, nie abgeschrieben — eine abgeschriebene
Liste ist blind fuer Zuwachs.
"""

from __future__ import annotations

import ast
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "tests" / "proof_corpus"

VERDICTS = frozenset(
    {"PASS", "FAIL", "SCHLAFEND", "STEHT_AUS", "KANN_NICHT_BEZEUGEN", "PRUEFEN"}
)


@dataclass(frozen=True)
class Verdict:
    state: str
    branch: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in VERDICTS:
            raise ValueError(f"unbekanntes Urteil {self.state!r}")


def load_judge(name: str) -> ModuleType:
    return importlib.import_module(f"scripts.proof_judges.{name}")


def corpus_for(name: str) -> tuple[tuple[str, dict], ...]:
    """``(run_id, evidenz)`` je aufgezeichnetem echten Artefakt."""
    folder = CORPUS_ROOT / name
    if not folder.exists():
        return ()
    return tuple(
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(folder.glob("*.json"))
    )


def dig(evidence: dict, dotted: str):
    """``mutations.partiallyRepairedChartUrls`` aufloesen; ``None``, wenn weg."""
    node = evidence
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def has_path(evidence: dict, dotted: str) -> bool:
    node = evidence
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


class VacuityError(Exception):
    """Die Zweig-Ableitung hat ihre Untergrenze unterschritten."""


def judge_names() -> frozenset[str]:
    """Alle im Ledger benannten Urteiler — abgeleitet, nicht gelistet."""
    from scripts.proof_ledger import load_entries

    return frozenset(entry.judge for entry in load_entries() if entry.judge)


def declared_branches(name: str) -> frozenset[str]:
    """Zweig-Labels aus dem QUELLTEXT des Urteilers ableiten.

    Nicht abschreiben. Eine Liste, die eine Kopie der bewachten Struktur ist,
    kann genau die Drift nicht fangen, vor der sie warnt — gemessen am
    2026-08-22, als #5013 ein neuntes ``mutations``-Feld hinzufuegte und der
    hartkodierte Kopplungstest gruen blieb.
    """
    module = load_judge(name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    labels: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if called != "Verdict":
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "branch"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                labels.add(keyword.value.value)
    if len(labels) < 2:
        raise VacuityError(
            f"{name}: nur {len(labels)} Zweig-Label(s) gefunden — der Parser ist "
            "kaputt, oder der Urteiler hat keine Verzweigung. Beides ist ein "
            "Befund, kein Ergebnis."
        )
    return frozenset(labels)
